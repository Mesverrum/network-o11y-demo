# Kafka plugin validation lab

Dedicated **private** EC2 (not the colocated Clos host) that builds
`Mesverrum/grafana-kafka-datasource` (`feat/enable-grafana-alerting`), runs
Grafana + Kafka via the plugin's docker-compose, produces JSON messages, and
evaluates a Grafana-managed alert against `QueryData`.

Unsigned plugins cannot load on Grafana Cloud. This is self-hosted Grafana in
development mode. Amazon Linux 2023 has no `docker-compose-plugin` RPM; userdata
installs Compose v2 from GitHub into `/usr/local/lib/docker/cli-plugins`.

## Bring-up

```bash
# from WSL after aws sso login --profile mvr --use-device-code
bash local/scripts/kafka-plugin-lab-discover.sh
bash local/scripts/kafka-plugin-lab-up.sh
```

Bootstrap takes ~15–25 minutes (Node/Go install, `pnpm test:ci`, `mage testRace`,
compose build). Watch:

```bash
aws ssm start-session --target "$(terraform -chdir=terraform/kafka-plugin-lab output -raw instance_id)"
# then: sudo cat /var/lib/kafka-plugin-lab/status
# sudo tail -f /var/log/kafka-plugin-lab-bootstrap.log
```

Grafana UI:

```bash
aws ssm start-session --target <instance-id> \
  --document-name AWS-StartPortForwardingSession \
  --parameters portNumber=3000,localPortNumber=3000
```

Open http://127.0.0.1:3000 (anonymous Admin).

## Tear down

```bash
bash local/scripts/kafka-plugin-lab-down.sh
```
