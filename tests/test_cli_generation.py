import subprocess
import sys
from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "basic"
DEFINITIONS_DIR = FIXTURE_DIR / "definitions.example"


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
