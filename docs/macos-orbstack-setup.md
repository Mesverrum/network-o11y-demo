# Running the local lab on macOS (OrbStack Linux VM)

> **Why this doc exists:** ContainerLab does **not** run natively on macOS. It
> needs a Linux kernel (netns/veth/bridges), and there is no darwin binary
> (`brew install containerlab` has no formula; `get.containerlab.dev` reports
> *"No prebuilt binary for darwin-arm64"*). The
> [ContainerLab macOS guide](https://containerlab.dev/macos/) recommends running
> everything inside a Linux VM. This page documents the **OrbStack** path that
> the rest of `local/` assumes on a Mac.

This replaces the older "Docker Desktop on macOS" assumption in
[`local/README.md`](../local/README.md). Docker Desktop alone is **not enough**
on a Mac, because ContainerLab itself cannot run on the host — the whole lab
(ContainerLab + the Docker Compose collectors) runs inside one Linux VM.

Tested on Apple Silicon (M-series, arm64), macOS 15, 2026-07.

## 1. Install OrbStack + a Linux VM

```bash
brew install --cask orbstack        # then open OrbStack once to finish setup
```

Open the OrbStack app once and approve the macOS admin prompt (privileged
network helper). In onboarding, enable **Linux** (and **Docker**). Then create
an arm64 Ubuntu machine and run every command below inside it:

```bash
orb create ubuntu                    # arm64 Ubuntu machine (OrbStack may create one during setup)
orb -m ubuntu                        # shell into the VM
```

OrbStack shares your macOS `/Users` into the VM automatically, but **do not run
the lab from that shared mount** — clone to the VM's native disk instead (see
step 3).

## 2. Install the toolchain inside the VM

OrbStack machines do **not** run a Docker daemon by default — install one in the
VM so ContainerLab and Compose share a single engine on the same kernel:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 make gettext-base curl ca-certificates
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"      # log out/in (or reconnect with `orb -m ubuntu`) to take effect

# ContainerLab (linux arm64 binary)
bash -c "$(curl -sL https://get.containerlab.dev)"

# mikefarah yq (the apt package is a different tool)
sudo curl -sL -o /usr/local/bin/yq \
  https://github.com/mikefarah/yq/releases/latest/download/yq_linux_arm64
sudo chmod +x /usr/local/bin/yq
```

`python3` ships with Ubuntu. Verify: `docker version`, `containerlab version`,
`yq --version`, `make --version`, `envsubst --version`.

## 3. Clone to the VM's native filesystem

Running from the shared `/Users` mount causes the same class of problems
ContainerLab hits on WSL `/mnt/c` (startup-config commit failures, uid drift).
Clone to the VM's native disk:

```bash
cd ~
git clone https://github.com/Mesverrum/network-o11y-demo.git
cd network-o11y-demo/local
```

## 4. Configure and bring up

```bash
cp .env.example .env                 # set GC_OTLP_URL / GC_OTLP_ACCOUNT / GC_OTLP_KEY
cp groups/srl.env.sample groups/srl.env
sed -i 's/\r$//' .env groups/srl.env # sample files may carry CRLF -> breaks shell sourcing

make generate
make check                           # docker, containerlab, yq, envsubst, .env
make up                              # ~10-15 min cold on Apple Silicon (amd64 emulation for SR Linux)
```

`make up` deploys the ContainerLab fabric, then the collectors, then runs
discovery. Expect **12 containers** (5 fabric + 7 collectors).

## 5. macOS/OrbStack-specific gotchas

These differ from the Linux/WSL reference platform and will bite on a Mac:

| Symptom | Cause | Fix |
|---|---|---|
| `make generate` fails with `$'\r': command not found` | sample `.env`/`groups` files have CRLF | `sed -i 's/\r$//' .env groups/srl.env` |
| `make up` fails on `topology_exporter` (`pull access denied`) | image is a local build, not on a registry | `make topology-exporter-image`, then `make stabilize` |
| `make up` fails: *"containers already exist — add --reconfigure"* | fabric already deployed | **never** `--reconfigure` (SIGTERMs all nodes); run `make stabilize` |
| discovery writes `{}` / `chtimes: operation not permitted` / `Permission denied` on `state/` | OrbStack maps your Mac user to **uid 501**, but ktranslate containers run as **uid 1000** and `run-discovery.sh` assumes it runs as root/1000 | run discovery as root: **`sudo make discover GROUP=srl`** (keep `config/` owned by your user so `make generate` still works) |
| SR Linux nodes exit 143 | SIGTERM (Docker restart, resource saver), **not** OOM | `make stabilize` |

On the Linux/WSL reference platform the login user *is* uid 1000, so the
discovery step "just works" there; the `sudo make discover` workaround is
specific to the OrbStack uid mapping.

## 6. Resources

- Give the VM **10–12 GB+** RAM. A 16 GB Mac with 10+ GB for the VM is the floor;
  Apple Silicon runs the `linux/amd64` SR Linux image under emulation (slower
  first boot, ~15 min cold `make up`).
- First pull of `ghcr.io/nokia/srlinux:24.10.1` is ~1.3 GiB.

## 7. Verify

`make status`, then in Grafana Cloud → Explore → Prometheus. Note the local
OTLP/ktranslate path uses per-metric names, **not** `kentik_snmp_DeviceMetrics`:

```promql
kentik_snmp_CPU                                    # spine1, leaf1, leaf2
kentik_snmp_tBgpPeerNgConnState                    # 6 = established
topk(20, network_io_by_flow_bytes)                 # NetFlow (after `make traffic`)
count by (device) (network_topology_device_info)   # topology (label is `device`)
```
