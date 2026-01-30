#!/usr/bin/env python3
"""
Deterministic and auditable Grafana Alloy configuration generator.
Combines host, scrape, and endpoint definitions into complete configs.
"""

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from importlib import resources
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path

import yaml
from jinja2 import Template


ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")
IDENTIFIER_PATTERN = re.compile(r"[^a-zA-Z0-9_]")


def warn(message):
    """Emit a warning message."""
    print(f"Warning: {message}")


def error(message):
    """Emit an error message and exit."""
    print(f"Error: {message}")
    sys.exit(1)


def resolve_env_vars(value, resolve_env):
    """Replace ${VAR} with environment variable values when requested."""
    if not resolve_env or not isinstance(value, str):
        return value

    def replacer(match):
        var_name = match.group(1)
        resolved = os.environ.get(var_name)
        if resolved is None:
            warn(f"Environment variable ${{{var_name}}} not set")
            return f"${{{var_name}}}"
        return resolved

    return ENV_VAR_PATTERN.sub(replacer, value)


def resolve_all_env_vars(data, resolve_env):
    """Recursively resolve environment variables in YAML data."""
    if isinstance(data, dict):
        return {key: resolve_all_env_vars(value, resolve_env) for key, value in data.items()}
    if isinstance(data, list):
        return [resolve_all_env_vars(item, resolve_env) for item in data]
    if isinstance(data, str):
        return resolve_env_vars(data, resolve_env)
    return data


def to_identifier(value):
    """Convert a string to a valid Alloy identifier (letters, numbers, underscores)."""
    if value is None:
        return "unnamed"
    cleaned = IDENTIFIER_PATTERN.sub("_", str(value))
    cleaned = cleaned.strip("_")
    if not cleaned:
        cleaned = "unnamed"
    if cleaned[0].isdigit():
        cleaned = f"n_{cleaned}"
    return cleaned


def load_yaml(filepath, resolve_env):
    """Load a YAML file and optionally resolve environment variables."""
    with open(filepath, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if data is None:
        warn(f"{filepath} is empty or invalid, skipping")
        return None

    if not isinstance(data, dict):
        error(f"{filepath} must contain a YAML object with a 'name' field")

    return resolve_all_env_vars(data, resolve_env)


def load_all_definitions(def_type, resolve_env, definitions_root):
    """Load all YAML files from a definitions subdirectory in stable order."""
    definitions = {}
    path = Path(definitions_root) / def_type

    if not path.exists():
        return definitions

    yaml_files = sorted(path.glob("*.yaml"), key=lambda p: p.name.lower())
    for yaml_file in yaml_files:
        data = load_yaml(yaml_file, resolve_env)
        if data is None:
            continue
        if "name" not in data:
            error(f"{yaml_file} is missing required field 'name'")
        definitions[data["name"]] = data

    return definitions


def stable_unique(items):
    """Return a list with duplicates removed while preserving order."""
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def normalize_text(text):
    """Normalize newlines to LF and ensure a trailing newline."""
    normalized = text.replace("\r\n", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def hash_text(text):
    """Compute a SHA256 hash for a text blob."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_file(path):
    """Compute a SHA256 hash for a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_template_text(template_name):
    """Read a template either from the local repo or packaged resources."""
    local_path = Path("templates") / template_name
    if local_path.exists():
        return local_path.read_text(encoding="utf-8")
    return (
        resources.files("alloy_config_generator")
        .joinpath("templates", template_name)
        .read_text(encoding="utf-8")
    )


def write_text(path, content):
    """Write text content using LF newlines for determinism."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def clean_outputs(output_dir, host_names, clean_alloy, clean_configmap):
    """Remove generated outputs for hosts not in the current run."""
    host_set = set(host_names)
    if clean_alloy:
        for path in output_dir.glob("*.alloy"):
            if path.stem not in host_set:
                path.unlink(missing_ok=True)
    if clean_configmap:
        for path in output_dir.glob("*.configmap.yaml"):
            stem = path.name.replace(".configmap.yaml", "")
            if stem not in host_set:
                path.unlink(missing_ok=True)


def clean_k8s_host_dirs(k8s_dir, host_names):
    """Remove per-host Kubernetes output directories not in the current run."""
    host_set = set(host_names)
    if not k8s_dir.exists():
        return
    for path in k8s_dir.iterdir():
        if not path.is_dir():
            continue
        if path.name not in host_set:
            shutil.rmtree(path, ignore_errors=True)


def relativize(path, root):
    """Return a stable relative path using POSIX separators."""
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    try:
        rel_path = path_resolved.relative_to(root_resolved)
    except ValueError:
        rel_path = Path(os.path.relpath(path_resolved, root_resolved))
    return rel_path.as_posix()


def get_git_commit():
    """Return the current git commit hash if available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def collect_input_hashes(definitions_root):
    """Collect hashes for all inputs that affect generation."""
    root = Path.cwd()
    definitions_root = Path(definitions_root)
    input_paths = []
    if definitions_root.exists():
        input_paths = sorted(definitions_root.glob("**/*.yaml"), key=lambda p: p.as_posix().lower())
    input_paths.extend(
        [
            root / "generate.py",
            root / "alloy_config_generator/cli.py",
        ]
    )

    inputs = {}
    for path in input_paths:
        if not path.exists():
            continue
        rel_path = path.relative_to(root).as_posix()
        inputs[rel_path] = hash_file(path)

    templates_dir = root / "templates"
    if templates_dir.exists():
        template_paths = sorted(templates_dir.glob("*.j2"), key=lambda p: p.as_posix().lower())
        for path in template_paths:
            rel_path = path.relative_to(root).as_posix()
            inputs[rel_path] = hash_file(path)
    else:
        for template_name in ("config.alloy.j2", "argocd.application.j2"):
            try:
                inputs[f"package:templates/{template_name}"] = hash_text(
                    read_template_text(template_name)
                )
            except FileNotFoundError:
                continue
    return inputs


def compute_required_signals(scrapes):
    """Determine which signal types are required by the selected scrapes."""
    required = set()
    for scrape in scrapes:
        scrape_type = scrape.get("type")
        if scrape_type in {"logs", "logs-journal", "logs-k8s"}:
            required.add("loki")
        if scrape_type in {"metrics", "metrics-k8s", "metrics-k8s-pods"}:
            required.add("prometheus")
    return required


def endpoint_enabled(endpoint, signal_type):
    """Check whether an endpoint is enabled for a given signal type."""
    signal_config = endpoint.get(signal_type)
    if not isinstance(signal_config, dict):
        return False
    return bool(signal_config.get("enabled", True))


def resolve_endpoints_for_host(host, endpoints, required_signals, host_name):
    """Resolve endpoint configuration(s) for a host with validation."""
    endpoints_to_use = {"loki": [], "prometheus": []}

    if "endpoints" in host:
        for signal_type, endpoint_names in host["endpoints"].items():
            if isinstance(endpoint_names, str):
                endpoint_names = [endpoint_names]
            if signal_type not in endpoints_to_use:
                warn(f"Host '{host_name}' references unsupported endpoint type '{signal_type}'")
                continue
            for endpoint_name in endpoint_names:
                if endpoint_name not in endpoints:
                    error(f"Endpoint '{endpoint_name}' not found for host '{host_name}'")
                endpoint = endpoints[endpoint_name]
                if endpoint_enabled(endpoint, signal_type):
                    endpoints_to_use[signal_type].append(endpoint)
                else:
                    warn(
                        f"Endpoint '{endpoint_name}' is disabled for '{signal_type}' "
                        f"and will be skipped for host '{host_name}'"
                    )
    elif "endpoint" in host:
        endpoint_name = host["endpoint"]
        if endpoint_name not in endpoints:
            error(f"Endpoint '{endpoint_name}' not found for host '{host_name}'")
        endpoint = endpoints[endpoint_name]
        for signal_type in endpoints_to_use:
            if endpoint_enabled(endpoint, signal_type):
                endpoints_to_use[signal_type].append(endpoint)
            elif signal_type in required_signals:
                warn(
                    f"Endpoint '{endpoint_name}' is disabled for required signal '{signal_type}' "
                    f"on host '{host_name}'"
                )
    else:
        error(f"Host '{host_name}' must have 'endpoint' or 'endpoints'")

    for signal_type in required_signals:
        if not endpoints_to_use.get(signal_type):
            error(
                f"Host '{host_name}' requires '{signal_type}' endpoints but none are enabled. "
                "Check endpoint definitions and enabled flags."
            )

    return endpoints_to_use


def validate_scrape(scrape, scrape_name, host_name):
    """Validate and apply safe defaults to a scrape definition."""
    scrape_type = scrape.get("type")
    if scrape_type not in {"logs", "logs-journal", "logs-k8s", "metrics", "metrics-k8s", "metrics-k8s-pods"}:
        error(f"Scrape '{scrape_name}' on host '{host_name}' has unsupported type '{scrape_type}'")

    scrape.setdefault("labels", {})
    if "job" not in scrape["labels"]:
        scrape["labels"]["job"] = scrape_name
        warn(f"Scrape '{scrape_name}' on host '{host_name}' missing labels.job; defaulting to '{scrape_name}'")

    if scrape_type in {"metrics", "metrics-k8s"}:
        scrape.setdefault("scrape_interval", "30s")
    if scrape_type == "metrics-k8s-pods":
        scrape.setdefault("scrape_interval", "30s")
        scrape.setdefault("role", "pod")

    if scrape_type == "metrics" and not scrape.get("targets") and not scrape.get("endpoint"):
        error(f"Scrape '{scrape_name}' on host '{host_name}' must define 'endpoint' or 'targets'")

    if scrape_type == "logs" and not scrape.get("targets") and not scrape.get("paths"):
        error(f"Scrape '{scrape_name}' on host '{host_name}' must define 'paths' or 'targets'")

    if scrape_type == "logs-journal":
        scrape.setdefault("path", "/var/log/journal")
        scrape.setdefault("max_age", "12h0m0s")
        scrape.setdefault("relabel_rules", [])

    if scrape_type == "logs-k8s":
        scrape.setdefault("role", "pod")


def resolve_scrapes_for_host(host, scrapes, stacks, host_name):
    """Resolve scrapes for a host, including stack expansion and validation."""
    host_scrape_names = list(host.get("scrapes", []))

    if "stack" in host:
        stack_name = host["stack"]
        if stack_name not in stacks:
            error(f"Stack '{stack_name}' not found for host '{host_name}'")
        stack_scrapes = stacks[stack_name].get("scrapes", [])
        host_scrape_names = stable_unique(stack_scrapes + host_scrape_names)

    if not host_scrape_names:
        error(f"Host '{host_name}' has no scrapes configured")

    resolved_scrapes = []
    for scrape_name in host_scrape_names:
        if scrape_name not in scrapes:
            error(f"Scrape '{scrape_name}' not found for host '{host_name}'")
        scrape = copy.deepcopy(scrapes[scrape_name])
        validate_scrape(scrape, scrape_name, host_name)
        scrape["id"] = to_identifier(scrape.get("name", scrape_name))
        if scrape.get("targets"):
            for target in scrape["targets"]:
                target_name = target.get("name") or target.get("address") or "target"
                target["id"] = to_identifier(target_name)
        resolved_scrapes.append(scrape)

    return resolved_scrapes


def render_configmap(host_name, config_text, name_template, namespace, config_key):
    """Render a Kubernetes ConfigMap containing the Alloy configuration."""
    configmap_name = name_template.format(host=host_name)
    config_body = config_text.rstrip("\n")
    indented_body = textwrap.indent(config_body, "    ") if config_body else "    "

    lines = [
        "apiVersion: v1",
        "kind: ConfigMap",
        "metadata:",
        f"  name: {configmap_name}",
    ]
    if namespace:
        lines.append(f"  namespace: {namespace}")
    lines.extend(
        [
            "  labels:",
            "    app.kubernetes.io/name: alloy",
            "    app.kubernetes.io/managed-by: alloy-config-generator",
            f"    alloy-config/host: {host_name}",
            "data:",
            f"  {config_key}: |-",
            indented_body,
        ]
    )
    return "\n".join(lines) + "\n"


def generate_config(host_name, hosts, endpoints, scrapes, stacks, template, include_timestamp):
    """Generate Alloy config for a specific host."""
    if host_name not in hosts:
        available = ", ".join(sorted(hosts.keys()))
        error(f"Host '{host_name}' not found. Available hosts: {available}")

    host = copy.deepcopy(hosts[host_name])
    host.setdefault("extra_labels", {})
    host_namespace = host.get("namespace")

    host_scrapes = resolve_scrapes_for_host(host, scrapes, stacks, host_name)
    required_signals = compute_required_signals(host_scrapes)
    endpoints_to_use = resolve_endpoints_for_host(host, endpoints, required_signals, host_name)
    for endpoint_list in endpoints_to_use.values():
        for endpoint in endpoint_list:
            endpoint["id"] = to_identifier(endpoint.get("name"))

    timestamp = None
    if include_timestamp:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    rendered = template.render(
        host=host,
        loki_endpoints=endpoints_to_use.get("loki", []),
        prometheus_endpoints=endpoints_to_use.get("prometheus", []),
        scrapes=host_scrapes,
        timestamp=timestamp,
    )

    return normalize_text(rendered)


def write_manifests(output_dir, outputs, manifest_enabled, settings, definitions_root):
    """Write deterministic manifest files for auditability."""
    if not manifest_enabled:
        return

    root = Path.cwd().resolve()
    inputs = collect_input_hashes(definitions_root)
    git_commit = get_git_commit()

    manifest = {
        "generator": {
            "script": "generate.py",
            "git_commit": git_commit,
            "python": sys.version.split()[0],
            "settings": settings,
        },
        "inputs": inputs,
        "outputs": outputs,
    }

    manifest_json_path = output_dir / "manifest.json"
    write_text(manifest_json_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    sha_entries = []
    for host_outputs in outputs.values():
        for artifact in host_outputs.values():
            sha_entries.append((artifact["path"], artifact["sha256"]))

    sha_entries.sort(key=lambda item: item[0])
    sha_lines = [f"{sha}  {path}" for path, sha in sha_entries]
    manifest_sha_path = output_dir / "manifest.sha256"
    write_text(manifest_sha_path, "\n".join(sha_lines) + ("\n" if sha_lines else ""))

    rel_json = relativize(manifest_json_path, root)
    rel_sha = relativize(manifest_sha_path, root)
    print(f"Generated: {rel_json}")
    print(f"Generated: {rel_sha}")


def parse_args():
    """Parse command line arguments."""
    try:
        cli_version = pkg_version("alloy-config-generator")
    except PackageNotFoundError:
        cli_version = "0.0.0"
    parser = argparse.ArgumentParser(
        description="Deterministic Grafana Alloy configuration generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"alloygen {cli_version}",
        help="Show version and exit",
    )
    parser.add_argument("host", nargs="?", help="Host name to generate")
    parser.add_argument("--all", action="store_true", dest="generate_all", help="Generate configs for all hosts")
    parser.add_argument("--output-dir", default="generated", help="Output directory for generated artifacts")
    parser.add_argument(
        "--definitions-dir",
        default=os.environ.get("ALLOYGEN_DEFINITIONS_DIR", "definitions"),
        help="Definitions directory (can also use ALLOYGEN_DEFINITIONS_DIR)",
    )
    parser.add_argument(
        "--format",
        choices=["alloy", "configmap", "both", "argocd", "all"],
        default="alloy",
        help="Output format to generate",
    )
    parser.add_argument(
        "--configmap-name-template",
        default="alloy-config-{host}",
        help="ConfigMap name template (supports {host})",
    )
    parser.add_argument("--configmap-key", default="config.alloy", help="Key name for the config in the ConfigMap")
    parser.add_argument("--namespace", default=None, help="Kubernetes namespace for generated ConfigMaps")
    parser.add_argument(
        "--resolve-env",
        action="store_true",
        help="Resolve ${VAR} environment variables at generation time (reduces determinism)",
    )
    parser.add_argument(
        "--include-timestamp",
        action="store_true",
        help="Include a generation timestamp in configs (reduces determinism)",
    )
    parser.add_argument("--no-manifest", action="store_true", help="Do not generate manifest files")
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include hosts marked enabled: false",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove generated outputs for hosts that are not part of this run",
    )

    parser.add_argument(
        "--alloy-output-dir",
        default=None,
        help="Output directory for .alloy files (defaults to --output-dir)",
    )
    parser.add_argument(
        "--k8s-output-dir",
        default=None,
        help="Output directory for Kubernetes manifests (defaults to --output-dir)",
    )

    parser.add_argument(
        "--argocd-repo-url",
        default=None,
        help="Repo URL for Argo CD Applications (required for --format argocd/all)",
    )
    parser.add_argument(
        "--argocd-target-revision",
        default="main",
        help="Target revision for Argo CD Applications",
    )
    parser.add_argument(
        "--argocd-path-base",
        default=None,
        help="Base path in repo for generated Kubernetes manifests",
    )
    parser.add_argument(
        "--argocd-project",
        default="monitoring",
        help="Argo CD project name",
    )
    parser.add_argument(
        "--argocd-app-namespace",
        default="argocd",
        help="Namespace for Argo CD Application objects",
    )
    parser.add_argument(
        "--argocd-dest-namespace",
        default="monitoring",
        help="Destination namespace for Argo CD Applications",
    )
    parser.add_argument(
        "--argocd-dest-server",
        default="https://kubernetes.default.svc",
        help="Destination server for Argo CD Applications",
    )

    args = parser.parse_args()

    if args.generate_all and args.host:
        error("Specify either a host name or --all, not both")
    if not args.generate_all and not args.host:
        parser.print_help()
        sys.exit(1)

    return args


def main():
    """Main entry point."""
    args = parse_args()

    # Load all definitions with stable ordering
    definitions_dir = Path(args.definitions_dir)
    if not definitions_dir.exists():
        error(
            "Definitions directory not found. Copy definitions.example to definitions, "
            "or pass --definitions-dir / set ALLOYGEN_DEFINITIONS_DIR."
        )
    endpoints = load_all_definitions("endpoints", args.resolve_env, definitions_dir)
    scrapes = load_all_definitions("scrapes", args.resolve_env, definitions_dir)
    hosts = load_all_definitions("hosts", args.resolve_env, definitions_dir)
    stacks = load_all_definitions("stacks", args.resolve_env, definitions_dir)

    # Load templates
    template = Template(read_template_text("config.alloy.j2"))

    argocd_template = None
    output_dir = Path(args.output_dir)

    generate_alloy = args.format in {"alloy", "both", "all"}
    generate_configmap = args.format in {"configmap", "both", "all", "argocd"}
    generate_argocd = args.format in {"argocd", "all"}

    if generate_argocd:
        if not args.argocd_repo_url:
            error("--argocd-repo-url is required when generating Argo CD applications")
        argocd_template = Template(read_template_text("argocd.application.j2"))

    output_dir.mkdir(parents=True, exist_ok=True)

    root = Path.cwd().resolve()
    if not args.include_disabled:
        hosts = {
            name: data
            for name, data in hosts.items()
            if data.get("enabled", True)
        }
    if not hosts:
        error("No enabled hosts found. Use --include-disabled to generate disabled hosts.")

    host_names = sorted(hosts.keys()) if args.generate_all else [args.host]

    if generate_argocd and args.k8s_output_dir is None:
        k8s_output_dir = output_dir / "k8s"
    else:
        k8s_output_dir = Path(args.k8s_output_dir) if args.k8s_output_dir else output_dir

    if generate_argocd and args.alloy_output_dir is None:
        alloy_output_dir = output_dir / "alloy"
    else:
        alloy_output_dir = Path(args.alloy_output_dir) if args.alloy_output_dir else output_dir

    if generate_alloy:
        alloy_output_dir.mkdir(parents=True, exist_ok=True)
    if generate_configmap or generate_argocd:
        k8s_output_dir.mkdir(parents=True, exist_ok=True)

    k8s_per_host = generate_argocd

    outputs = {}
    if args.clean:
        if generate_alloy:
            clean_outputs(alloy_output_dir, host_names, clean_alloy=True, clean_configmap=False)
        if generate_configmap and not k8s_per_host:
            clean_outputs(k8s_output_dir, host_names, clean_alloy=False, clean_configmap=True)
        if k8s_per_host:
            clean_k8s_host_dirs(k8s_output_dir, host_names)
    for host_name in host_names:
        config = generate_config(
            host_name=host_name,
            hosts=hosts,
            endpoints=endpoints,
            scrapes=scrapes,
            stacks=stacks,
            template=template,
            include_timestamp=args.include_timestamp,
        )

        host_outputs = {}
        k8s_host_dir = k8s_output_dir / host_name if k8s_per_host else k8s_output_dir
        if k8s_per_host:
            k8s_host_dir.mkdir(parents=True, exist_ok=True)
        if generate_alloy:
            output_filename = hosts[host_name].get("output_filename", f"{host_name}.alloy")
            alloy_path = alloy_output_dir / output_filename
            write_text(alloy_path, config)
            rel_alloy_path = relativize(alloy_path, root)
            host_outputs["alloy"] = {"path": rel_alloy_path, "sha256": hash_text(config)}
            print(f"Generated: {rel_alloy_path}")

        if generate_configmap:
            namespace = args.namespace
            if not namespace:
                namespace = hosts[host_name].get("namespace")
            name_template = args.configmap_name_template
            if hosts[host_name].get("configmap_name"):
                name_template = hosts[host_name]["configmap_name"]
            configmap_text = render_configmap(
                host_name=host_name,
                config_text=config,
                name_template=name_template,
                namespace=namespace,
                config_key=args.configmap_key,
            )
            configmap_text = normalize_text(configmap_text)
            configmap_path = k8s_host_dir / f"{host_name}.configmap.yaml"
            write_text(configmap_path, configmap_text)
            rel_configmap_path = relativize(configmap_path, root)
            host_outputs["configmap"] = {"path": rel_configmap_path, "sha256": hash_text(configmap_text)}
            print(f"Generated: {rel_configmap_path}")

        if generate_argocd:
            if args.argocd_path_base:
                argocd_path_base = Path(args.argocd_path_base)
            else:
                argocd_path_base = Path(relativize(k8s_output_dir, root))
            argocd_source_path = (argocd_path_base / host_name).as_posix()
            argocd_text = argocd_template.render(
                argocd_project=args.argocd_project,
                argocd_app_namespace=args.argocd_app_namespace,
                argocd_dest_namespace=args.argocd_dest_namespace,
                argocd_dest_server=args.argocd_dest_server,
                argocd_app_name=f"alloy-{host_name}",
                argocd_repo_url=args.argocd_repo_url,
                argocd_target_revision=args.argocd_target_revision,
                argocd_source_path=argocd_source_path,
            )
            argocd_text = normalize_text(argocd_text)
            argocd_path = k8s_host_dir / f"{host_name}.argocd-app.yaml"
            write_text(argocd_path, argocd_text)
            rel_argocd_path = relativize(argocd_path, root)
            host_outputs["argocd_app"] = {"path": rel_argocd_path, "sha256": hash_text(argocd_text)}
            print(f"Generated: {rel_argocd_path}")

        outputs[host_name] = host_outputs

    settings = {
        "all_hosts": args.generate_all,
        "format": args.format,
        "resolve_env": args.resolve_env,
        "include_timestamp": args.include_timestamp,
        "configmap_name_template": args.configmap_name_template,
        "configmap_key": args.configmap_key,
        "namespace": args.namespace,
        "definitions_dir": args.definitions_dir,
        "output_dir": output_dir.as_posix(),
        "alloy_output_dir": alloy_output_dir.as_posix(),
        "k8s_output_dir": k8s_output_dir.as_posix(),
        "argocd_repo_url": args.argocd_repo_url,
        "argocd_target_revision": args.argocd_target_revision,
        "argocd_path_base": args.argocd_path_base,
        "argocd_project": args.argocd_project,
        "argocd_app_namespace": args.argocd_app_namespace,
        "argocd_dest_namespace": args.argocd_dest_namespace,
        "argocd_dest_server": args.argocd_dest_server,
    }
    write_manifests(
        output_dir,
        outputs,
        manifest_enabled=not args.no_manifest,
        settings=settings,
        definitions_root=definitions_dir,
    )


if __name__ == "__main__":
    main()
