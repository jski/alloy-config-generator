# Alloy Config Generator

Deterministic configuration generator for Grafana Alloy.

## Quick Start

Copy example definitions (public-safe) and generate:
```bash
# macOS / Linux
cp -r definitions.example definitions

# Windows (Command Prompt)
xcopy /E /I definitions.example definitions
```

```bash
uv tool run --from alloy-config-generator alloygen --all --format both
```

Optional: install globally with uv (requires PATH setup):

```bash
uv tool install alloy-config-generator
alloygen --all
```

If you want to run from GitHub directly:
```bash
uv tool run --from "git+ssh://git@github.com/jski/alloy-config-generator.git@main" alloygen --all
```

If `uv` isn’t found, add the directory that contains `uv.exe` to your PATH.
On Windows, run this in Command Prompt:
```
where uv
```

If `alloygen` still isn’t found after `uv tool install`, use `uv tool list --verbose` to
locate `alloygen.exe` and add that folder to PATH (or stick with `uv tool run --from ...`).

Local (repo) usage:

```bash
python generate.py --all
```

Generate example outputs (deterministic, committed to repo):
```bash
python generate.py --examples
```

## Structure

```
definitions.example/ # public-safe example inputs
definitions/         # private, real configs (ignored by git)
  endpoints/         # where data is sent
  scrapes/           # what is collected
  hosts/             # which host uses what
  stacks/            # reusable scrape groups

templates/           # optional template overrides
generated/           # output (ignored by git)
  alloy/             # alloy configs (when using --format all/argocd)
  k8s/               # k8s manifests (when using --format all/argocd)
```

Templates are packaged with the tool. Create a local `templates/` folder only if you want to override them.

## Public / Private Repo Pattern

- Public repo ships `definitions.example/` with placeholder values.
- Private repo stores real `definitions/` (ignored in public).

Quick start for a new repo:
```bash
cp -r definitions.example definitions
```

You can also point to a different definitions directory:
```bash
alloygen --definitions-dir /path/to/definitions --all
```

Or set it once:
```bash
setx ALLOYGEN_DEFINITIONS_DIR C:\path\to\definitions
```

## Core Concepts

- **Endpoint**: a Loki/Prometheus destination
- **Scrape**: logs or metrics definition
- **Host**: deployment target (docker or kubernetes)
- **Stack**: reusable set of scrapes

## Minimal Example

Endpoint (`definitions/endpoints/local.yaml`):
```yaml
name: local
prometheus:
  enabled: true
  url: https://prom.example.com/api/v1/write
  auth_type: basic
  username: admin
  password: ${PROMETHEUS_PASSWORD}
```

Scrape (`definitions/scrapes/node.yaml`):
```yaml
name: node
type: metrics
endpoint: 127.0.0.1:9100
scrape_interval: 30s
metrics_path: /metrics
labels:
  job: node
```

Host (`definitions/hosts/host-01.yaml`):
```yaml
name: host-01
deployment_type: docker
endpoint: local
scrapes:
  - node
extra_labels:
  site: lan
configmap_name: alloy-config-host-01
```

Generate:
```bash
alloygen host-01
```

## Common Patterns

Redundant routing (multiple sources of truth):
```yaml
endpoints:
  prometheus: [optimus-grafana, bumblebee-grafana]
  loki: [optimus-grafana, bumblebee-grafana]
```

Multi-target scrape:
```yaml
targets:
  - name: node_a
    address: node-a:9100
  - name: node_b
    address: node-b:9100
```

## Output Formats

```bash
alloygen host-01 --format alloy
alloygen host-01 --format configmap --namespace monitoring
alloygen --all --format both
alloygen --all --format argocd --argocd-repo-url git@github.com:your/private-repo.git
alloygen --all --format all --argocd-repo-url git@github.com:your/private-repo.git
```

## Staging Hosts (Disable by Default)

Add `enabled: false` to a host to skip generation until it’s ready:

```yaml
name: new-host
enabled: false
```

Generate disabled hosts explicitly:
```bash
alloygen --all --include-disabled
```

## Cleaning Old Outputs

To remove generated configs for hosts that no longer exist:

```bash
alloygen --all --format both --clean
```

## Deterministic Defaults

- No timestamp unless `--include-timestamp`
- `${VAR}` placeholders preserved unless `--resolve-env`
- `generated/manifest.json` and `generated/manifest.sha256` provide audit hashes

## Private Values and Local Overrides

If you plan to open‑source this, keep real endpoints and generated outputs in a private repo. The public repo can contain only the generator, templates, and example definitions.

## Deployment Notes

- Docker: mount the generated `.alloy` into the container.
- Kubernetes: `--format configmap --namespace monitoring` and apply the file.
- Argo CD: use `--format argocd` (or `--format all`) to generate per-cluster Application manifests.

## Alerting (Starter Rules)

A minimal Prometheus ruleset lives at `alerts/prometheus.rules.yaml`. Import it into your Prometheus config to get basic “failure-first” alerts (host down, Alloy down, disk/memory pressure, kubelet scrape down).

## Contributing

I’m happy to accept new scrape targets and improvements. To keep the project stable and safe for all users:

- **Use example data only**: add new scrapes/endpoints/hosts under `definitions.example/` (no real domains, secrets, or internal IPs).
- **Keep it deterministic**: avoid timestamps, random values, or environment-only behavior in examples.
- **Add tests**: if you add a new scrape type or behavior, include/extend a fixture under `tests/fixtures/basic/` and add a pytest to cover it.
- **Prefer backward‑compatible changes**: avoid breaking existing field names or defaults; if you must, document it clearly.
- **Document the scrape**: add a short note in README (or a comment in the example YAML) explaining what it does and when to use it.

Run tests locally:
```bash
uv pip install -e ".[dev]"
uv run pytest -q
```

Ways to contribute (beyond scrapes):

- **Templates**: alternate config templates or deployment styles.
- **Output formats**: Helm, Kustomize, Terraform, Secrets, etc.
- **Validation rules**: schema checks and better error messages.
- **Example packs**: curated `definitions.example` sets for common stacks.
- **Docs**: integration guides and usage patterns.
- **Tests/fixtures**: edge cases and new scrape types.
- **Label conventions**: standard label sets for common platforms/exporters.

## Releases (PyPI)

1) Bump the version in `pyproject.toml` in your PR.
2) Merge the PR — CI builds artifacts on `main`.
3) The Release workflow promotes those artifacts, tags `vX.Y.Z`, publishes to PyPI, and creates a GitHub Release with auto‑generated notes.

Release notes live in GitHub Releases; PyPI will show the README and link back to GitHub for per‑version details.
