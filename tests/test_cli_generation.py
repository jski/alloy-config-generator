import subprocess
import sys
from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "basic"
DEFINITIONS_DIR = FIXTURE_DIR / "definitions.example"
POLICY_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "policy"
POLICY_DEFINITIONS_DIR = POLICY_FIXTURE_DIR / "definitions.example"


def run_cli(tmp_path, extra_args, no_manifest=True):
    out_dir = tmp_path / "out"
    cmd = [
        sys.executable,
        "-m",
        "alloy_config_generator",
        "--all",
        "--output-dir",
        str(out_dir),
        "--definitions-dir",
        str(DEFINITIONS_DIR),
        *extra_args,
    ]
    if no_manifest:
        cmd.append("--no-manifest")
    subprocess.run(cmd, check=True, cwd=FIXTURE_DIR)
    return out_dir


def run_cli_from_fixture(
    tmp_path, fixture_dir, definitions_dir, extra_args, no_manifest=True
):
    out_dir = tmp_path / "out"
    cmd = [
        sys.executable,
        "-m",
        "alloy_config_generator",
        "--all",
        "--output-dir",
        str(out_dir),
        "--definitions-dir",
        str(definitions_dir),
        *extra_args,
    ]
    if no_manifest:
        cmd.append("--no-manifest")
    subprocess.run(cmd, check=True, cwd=fixture_dir)
    return out_dir


def run_cli_with_definitions(
    definitions_dir, output_dir, capture_output=False, extra_args=None
):
    if extra_args is None:
        extra_args = []
    cmd = [
        sys.executable,
        "-m",
        "alloy_config_generator",
        "--all",
        "--output-dir",
        str(output_dir),
        "--definitions-dir",
        str(definitions_dir),
        "--format",
        "alloy",
        "--no-manifest",
        *extra_args,
    ]
    return subprocess.run(
        cmd,
        capture_output=capture_output,
        text=capture_output,
    )


def test_generates_alloy_and_configmap(tmp_path):
    out_dir = run_cli(tmp_path, ["--format", "both"])

    alloy_path = out_dir / "demo-cluster.alloy"
    configmap_path = out_dir / "demo-cluster.configmap.yaml"

    assert alloy_path.exists()
    assert configmap_path.exists()

    alloy_text = alloy_path.read_text(encoding="utf-8")
    assert 'prometheus.scrape "node"' in alloy_text
    assert 'url = "http://prom.example.com/api/v1/write"' in alloy_text

    configmap_text = configmap_path.read_text(encoding="utf-8")
    assert "kind: ConfigMap" in configmap_text
    assert "name: alloy-config-demo-cluster" in configmap_text
    assert "config.alloy: |-" in configmap_text


def test_generates_argocd_app(tmp_path):
    out_dir = run_cli(
        tmp_path,
        [
            "--format",
            "all",
            "--argocd-repo-url",
            "git@github.com:example/private.git",
            "--argocd-path-base",
            "generated/k8s",
        ],
    )

    configmap_path = out_dir / "k8s" / "demo-cluster" / "demo-cluster.configmap.yaml"
    app_path = out_dir / "k8s" / "demo-cluster" / "demo-cluster.argocd-app.yaml"

    assert configmap_path.exists()
    assert app_path.exists()

    app_text = app_path.read_text(encoding="utf-8")
    assert "kind: Application" in app_text
    assert "name: alloy-demo-cluster" in app_text
    assert "project: monitoring" in app_text
    assert "repoURL: git@github.com:example/private.git" in app_text
    assert "path: generated/k8s/demo-cluster" in app_text


def test_deterministic_outputs(tmp_path):
    out_a = run_cli(tmp_path / "run_a", ["--format", "both"])
    out_b = run_cli(tmp_path / "run_b", ["--format", "both"])

    files_a = sorted(p for p in out_a.rglob("*") if p.is_file())
    files_b = sorted(p for p in out_b.rglob("*") if p.is_file())

    rel_a = [p.relative_to(out_a).as_posix() for p in files_a]
    rel_b = [p.relative_to(out_b).as_posix() for p in files_b]
    assert rel_a == rel_b

    for rel in rel_a:
        text_a = (out_a / rel).read_text(encoding="utf-8")
        text_b = (out_b / rel).read_text(encoding="utf-8")
        assert text_a == text_b


def test_manifest_hashes(tmp_path):
    out_dir = run_cli(tmp_path, ["--format", "both"], no_manifest=False)

    manifest_path = out_dir / "manifest.json"
    sha_path = out_dir / "manifest.sha256"
    assert manifest_path.exists()
    assert sha_path.exists()

    import json
    import hashlib

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    outputs = manifest.get("outputs", {})
    assert outputs

    for host_outputs in outputs.values():
        for artifact in host_outputs.values():
            rel_path = artifact["path"]
            artifact_path = (FIXTURE_DIR / rel_path).resolve()
            actual_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            assert actual_hash == artifact["sha256"]


def test_manifest_hashes_with_relative_definitions_dir(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    cmd = [
        sys.executable,
        "-m",
        "alloy_config_generator",
        "--all",
        "--output-dir",
        str(out_dir),
        "--definitions-dir",
        "definitions.example",
        "--format",
        "both",
    ]
    monkeypatch.chdir(FIXTURE_DIR)
    subprocess.run(cmd, check=True)

    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()


def test_logs_journal_uses_identifier_safe_component_names(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: shockwave-grafana",
                "scrapes:",
                "  - systemd-journal",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "systemd-journal.yaml").write_text(
        "\n".join(
            [
                "name: systemd-journal",
                "type: logs-journal",
                "labels:",
                "  job: systemd-journal",
                "relabel_rules: []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "shockwave-grafana.yaml").write_text(
        "\n".join(
            [
                "name: shockwave-grafana",
                "loki:",
                "  enabled: true",
                "  url: https://loki.example.com/loki/api/v1/push",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "out"
    cmd = [
        sys.executable,
        "-m",
        "alloy_config_generator",
        "--all",
        "--output-dir",
        str(out_dir),
        "--definitions-dir",
        str(defs),
        "--format",
        "alloy",
        "--no-manifest",
    ]
    subprocess.run(cmd, check=True)

    alloy_text = (out_dir / "demo.alloy").read_text(encoding="utf-8")
    assert 'prometheus.relabel "systemd_journal"' in alloy_text
    assert "prometheus.remote_write.shockwave_grafana.receiver" in alloy_text
    assert 'replacement  = "systemd-journal"' in alloy_text
    assert 'prometheus.relabel "systemd-journal"' not in alloy_text
    assert "prometheus.remote_write.shockwave-grafana.receiver" not in alloy_text


def test_logs_syslog_renders_listener_and_static_labels(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: local",
                "scrapes:",
                "  - unifi-activity",
                "extra_labels:",
                "  site: lan",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "unifi-activity.yaml").write_text(
        "\n".join(
            [
                "name: unifi-activity",
                "type: logs-syslog",
                "listener_address: 0.0.0.0:5514",
                "protocol: udp",
                "syslog_format: raw",
                "max_message_length: 65536",
                "listener_labels:",
                "  protocol: udp",
                "  listener: unifi-activity-logging",
                "labels:",
                "  job: unifi-activity",
                "  component: unifi",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "local.yaml").write_text(
        "\n".join(
            [
                "name: local",
                "loki:",
                "  enabled: true",
                "  url: https://loki.example.com/loki/api/v1/push",
                "",
            ]
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "out"
    cmd = [
        sys.executable,
        "-m",
        "alloy_config_generator",
        "--all",
        "--output-dir",
        str(out_dir),
        "--definitions-dir",
        str(defs),
        "--format",
        "alloy",
        "--no-manifest",
    ]
    subprocess.run(cmd, check=True)

    alloy_text = (out_dir / "demo.alloy").read_text(encoding="utf-8")
    assert 'loki.relabel "unifi_activity_syslog"' in alloy_text
    assert 'loki.source.syslog "unifi_activity"' in alloy_text
    assert 'address = "0.0.0.0:5514"' in alloy_text
    assert 'protocol = "udp"' in alloy_text
    assert 'syslog_format = "raw"' in alloy_text
    assert "max_message_length = 65536" in alloy_text
    assert 'listener = "unifi-activity-logging"' in alloy_text
    assert 'regex = "__syslog_(.+)"' in alloy_text
    assert 'component = "unifi"' in alloy_text
    assert 'site = "lan"' in alloy_text


def test_logs_syslog_rejects_forbidden_raw_options(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: local",
                "scrapes:",
                "  - syslog",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "syslog.yaml").write_text(
        "\n".join(
            [
                "name: syslog",
                "type: logs-syslog",
                "listener_address: 0.0.0.0:5514",
                "syslog_format: raw",
                "use_incoming_timestamp: true",
                "labels:",
                "  job: syslog",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "local.yaml").write_text(
        "\n".join(
            [
                "name: local",
                "loki:",
                "  enabled: true",
                "  url: https://loki.example.com/loki/api/v1/push",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli_with_definitions(defs, tmp_path / "out", capture_output=True)
    assert result.returncode != 0
    assert (
        "cannot set 'use_incoming_timestamp' when syslog_format is 'raw'"
        in result.stdout
    )


def test_rejects_invalid_label_names(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: local",
                "scrapes:",
                "  - node",
                "extra_labels:",
                "  env-name: prod",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "node.yaml").write_text(
        "\n".join(
            [
                "name: node",
                "type: metrics",
                "endpoint: localhost:9100",
                "labels:",
                "  job: node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "local.yaml").write_text(
        "\n".join(
            [
                "name: local",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        "-m",
        "alloy_config_generator",
        "--all",
        "--output-dir",
        str(tmp_path / "out"),
        "--definitions-dir",
        str(defs),
        "--format",
        "alloy",
        "--no-manifest",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0
    assert "invalid label name" in result.stdout


def test_rejects_identifier_collisions_after_normalization(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoints:",
                "  prometheus: [shockwave-grafana, shockwave_grafana]",
                "scrapes:",
                "  - node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "node.yaml").write_text(
        "\n".join(
            [
                "name: node",
                "type: metrics",
                "endpoint: localhost:9100",
                "labels:",
                "  job: node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "shockwave-grafana.yaml").write_text(
        "\n".join(
            [
                "name: shockwave-grafana",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom-a.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "shockwave_grafana.yaml").write_text(
        "\n".join(
            [
                "name: shockwave_grafana",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom-b.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        "-m",
        "alloy_config_generator",
        "--all",
        "--output-dir",
        str(tmp_path / "out"),
        "--definitions-dir",
        str(defs),
        "--format",
        "alloy",
        "--no-manifest",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0
    assert "normalize to the same identifier" in result.stdout


def test_hashmod_relabel_rule_renders_modulus(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: local",
                "scrapes:",
                "  - node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "node.yaml").write_text(
        "\n".join(
            [
                "name: node",
                "type: metrics",
                "endpoint: localhost:9100",
                "labels:",
                "  job: node",
                "relabel_rules:",
                "  - action: hashmod",
                "    source_labels: [instance]",
                "    target_label: shard",
                "    modulus: 16",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "local.yaml").write_text(
        "\n".join(
            [
                "name: local",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        "-m",
        "alloy_config_generator",
        "--all",
        "--output-dir",
        str(tmp_path / "out"),
        "--definitions-dir",
        str(defs),
        "--format",
        "alloy",
        "--no-manifest",
    ]
    subprocess.run(cmd, check=True)
    alloy_text = (tmp_path / "out" / "demo.alloy").read_text(encoding="utf-8")
    assert 'action = "hashmod"' in alloy_text
    assert "modulus = 16" in alloy_text


def test_rejects_invalid_relabel_action(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: local",
                "scrapes:",
                "  - node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "node.yaml").write_text(
        "\n".join(
            [
                "name: node",
                "type: metrics",
                "endpoint: localhost:9100",
                "labels:",
                "  job: node",
                "relabel_rules:",
                "  - action: not-a-real-action",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "local.yaml").write_text(
        "\n".join(
            [
                "name: local",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        "-m",
        "alloy_config_generator",
        "--all",
        "--output-dir",
        str(tmp_path / "out"),
        "--definitions-dir",
        str(defs),
        "--format",
        "alloy",
        "--no-manifest",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0
    assert "invalid action" in result.stdout


def test_parses_metrics_endpoint_with_scheme_and_path(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: local",
                "scrapes:",
                "  - node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "node.yaml").write_text(
        "\n".join(
            [
                "name: node",
                "type: metrics",
                "endpoint: https://localhost:9100/metrics",
                "labels:",
                "  job: node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "local.yaml").write_text(
        "\n".join(
            [
                "name: local",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli_with_definitions(defs, tmp_path / "out", capture_output=True)
    assert result.returncode == 0
    alloy_text = (tmp_path / "out" / "demo.alloy").read_text(encoding="utf-8")
    assert '{"__address__" = "localhost:9100"}' in alloy_text
    assert 'metrics_path = "/metrics"' in alloy_text


def test_parses_metrics_endpoint_with_path_only(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: local",
                "scrapes:",
                "  - node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "node.yaml").write_text(
        "\n".join(
            [
                "name: node",
                "type: metrics",
                "endpoint: localhost:9100/metrics",
                "labels:",
                "  job: node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "local.yaml").write_text(
        "\n".join(
            [
                "name: local",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli_with_definitions(defs, tmp_path / "out", capture_output=True)
    assert result.returncode == 0
    alloy_text = (tmp_path / "out" / "demo.alloy").read_text(encoding="utf-8")
    assert '{"__address__" = "localhost:9100"}' in alloy_text
    assert 'metrics_path = "/metrics"' in alloy_text


def test_rejects_metrics_path_without_leading_slash(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: local",
                "scrapes:",
                "  - node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "node.yaml").write_text(
        "\n".join(
            [
                "name: node",
                "type: metrics",
                "endpoint: localhost:9100",
                "metrics_path: metrics",
                "labels:",
                "  job: node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "local.yaml").write_text(
        "\n".join(
            [
                "name: local",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli_with_definitions(defs, tmp_path / "out", capture_output=True)
    assert result.returncode != 0
    assert "metrics_path must start with '/'" in result.stdout


def test_renders_metrics_path_for_single_endpoint_scrape(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: local",
                "scrapes:",
                "  - node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "node.yaml").write_text(
        "\n".join(
            [
                "name: node",
                "type: metrics",
                "endpoint: localhost:9100",
                "metrics_path: /probe",
                "labels:",
                "  job: node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "local.yaml").write_text(
        "\n".join(
            [
                "name: local",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli_with_definitions(defs, tmp_path / "out", capture_output=True)
    assert result.returncode == 0

    alloy_text = (tmp_path / "out" / "demo.alloy").read_text(encoding="utf-8")
    assert 'metrics_path = "/probe"' in alloy_text


def test_rejects_conflicting_metrics_path_from_endpoint(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: local",
                "scrapes:",
                "  - node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "node.yaml").write_text(
        "\n".join(
            [
                "name: node",
                "type: metrics",
                "endpoint: https://localhost:9100/metrics",
                "metrics_path: /custom",
                "labels:",
                "  job: node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "local.yaml").write_text(
        "\n".join(
            [
                "name: local",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli_with_definitions(defs, tmp_path / "out", capture_output=True)
    assert result.returncode != 0
    assert "conflicting metrics_path values" in result.stdout


def test_host_label_policy_merge_precedence_static_mode(tmp_path):
    out_dir = run_cli_from_fixture(
        tmp_path,
        fixture_dir=POLICY_FIXTURE_DIR,
        definitions_dir=POLICY_DEFINITIONS_DIR,
        extra_args=["--format", "alloy"],
    )

    shockwave_alloy = (out_dir / "shockwave.alloy").read_text(encoding="utf-8")
    assert 'target_label = "site"' in shockwave_alloy
    assert 'replacement  = "rack-a"' in shockwave_alloy
    assert 'target_label = "host"' in shockwave_alloy
    assert 'replacement  = "shockwave"' in shockwave_alloy
    assert 'target_label = "env"' in shockwave_alloy
    assert 'replacement  = "prod"' in shockwave_alloy

    k8s_alloy = (out_dir / "dboraclevmwest.alloy").read_text(encoding="utf-8")
    assert 'target_label = "cluster"' in k8s_alloy
    assert 'replacement  = "dboraclevmwest"' in k8s_alloy


def test_host_label_policy_missing_file_falls_back_to_extra_labels(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: local",
                "scrapes:",
                "  - node",
                "extra_labels:",
                "  site: edge",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "node.yaml").write_text(
        "\n".join(
            [
                "name: node",
                "type: metrics",
                "endpoint: localhost:9100",
                "labels:",
                "  job: node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "local.yaml").write_text(
        "\n".join(
            [
                "name: local",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli_with_definitions(defs, tmp_path / "out", capture_output=True)
    assert result.returncode == 0
    alloy_text = (tmp_path / "out" / "demo.alloy").read_text(encoding="utf-8")
    assert 'target_label = "site"' in alloy_text
    assert 'replacement  = "edge"' in alloy_text
    assert 'target_label = "host"' not in alloy_text
    assert 'target_label = "cluster"' not in alloy_text


def test_relabel_policy_mode_wires_metrics_relabel_chain(tmp_path):
    out_dir = run_cli_from_fixture(
        tmp_path,
        fixture_dir=POLICY_FIXTURE_DIR,
        definitions_dir=POLICY_DEFINITIONS_DIR,
        extra_args=["--format", "alloy", "--label-policy-mode", "relabel"],
    )

    shockwave_alloy = (out_dir / "shockwave.alloy").read_text(encoding="utf-8")
    assert 'prometheus.relabel "host_policy" {' in shockwave_alloy
    assert "prometheus.relabel.host_policy.receiver" in shockwave_alloy
    assert "prometheus.remote_write.shockwave_grafana.receiver" in shockwave_alloy
    assert (
        'prometheus.relabel "node_exporter_docker" {\n'
        "  forward_to = [\n"
        "    prometheus.relabel.host_policy.receiver,\n"
        "  ]"
    ) in shockwave_alloy
    assert 'target_label = "host"' in shockwave_alloy
    assert 'replacement  = "shockwave"' in shockwave_alloy


def test_identifier_sanitization_for_hyphenated_fixture_names(tmp_path):
    out_dir = run_cli_from_fixture(
        tmp_path,
        fixture_dir=POLICY_FIXTURE_DIR,
        definitions_dir=POLICY_DEFINITIONS_DIR,
        extra_args=["--format", "alloy"],
    )
    shockwave_alloy = (out_dir / "shockwave.alloy").read_text(encoding="utf-8")
    assert 'prometheus.scrape "node_exporter_docker"' in shockwave_alloy
    assert 'prometheus.relabel "node_exporter_docker"' in shockwave_alloy
    assert "prometheus.remote_write.shockwave_grafana.receiver" in shockwave_alloy
    assert 'prometheus.scrape "node-exporter-docker"' not in shockwave_alloy
    assert "prometheus.remote_write.shockwave-grafana.receiver" not in shockwave_alloy


def test_escapes_backslashes_in_relabel_regex(tmp_path):
    defs = tmp_path / "definitions"
    (defs / "hosts").mkdir(parents=True)
    (defs / "scrapes").mkdir(parents=True)
    (defs / "endpoints").mkdir(parents=True)

    (defs / "hosts" / "demo.yaml").write_text(
        "\n".join(
            [
                "name: demo",
                "description: Demo host",
                "deployment_type: docker",
                "endpoint: local",
                "scrapes:",
                "  - node",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "scrapes" / "node.yaml").write_text(
        "\n".join(
            [
                "name: node",
                "type: metrics",
                "endpoint: localhost:9100",
                "labels:",
                "  job: node",
                "relabel_rules:",
                "  - action: replace",
                "    source_labels: [instance]",
                "    target_label: host",
                '    regex: "([^:]+)(?::\\\\d+)?"',
                '    replacement: "$1"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (defs / "endpoints" / "local.yaml").write_text(
        "\n".join(
            [
                "name: local",
                "prometheus:",
                "  enabled: true",
                "  url: https://prom.example.com/api/v1/write",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli_with_definitions(defs, tmp_path / "out", capture_output=True)
    assert result.returncode == 0
    alloy_text = (tmp_path / "out" / "demo.alloy").read_text(encoding="utf-8")
    assert 'regex = "([^:]+)(?::\\\\d+)?"' in alloy_text


def test_no_manifest_creates_no_manifest_files(tmp_path):
    out_dir = run_cli(tmp_path, ["--format", "both"], no_manifest=True)
    assert not (out_dir / "manifest.json").exists()
    assert not (out_dir / "manifest.sha256").exists()


def test_policy_fixture_outputs_are_deterministic(tmp_path):
    out_a = run_cli_from_fixture(
        tmp_path / "run_a",
        fixture_dir=POLICY_FIXTURE_DIR,
        definitions_dir=POLICY_DEFINITIONS_DIR,
        extra_args=["--format", "alloy"],
    )
    out_b = run_cli_from_fixture(
        tmp_path / "run_b",
        fixture_dir=POLICY_FIXTURE_DIR,
        definitions_dir=POLICY_DEFINITIONS_DIR,
        extra_args=["--format", "alloy"],
    )
    files_a = sorted(p for p in out_a.rglob("*") if p.is_file())
    files_b = sorted(p for p in out_b.rglob("*") if p.is_file())
    rel_a = [p.relative_to(out_a).as_posix() for p in files_a]
    rel_b = [p.relative_to(out_b).as_posix() for p in files_b]
    assert rel_a == rel_b
    for rel in rel_a:
        assert (out_a / rel).read_text(encoding="utf-8") == (out_b / rel).read_text(
            encoding="utf-8"
        )
