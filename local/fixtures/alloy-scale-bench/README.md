# Alloy 1-CPU scale bench

Harness: [`local/scripts/alloy-scale-bench.py`](../../scripts/alloy-scale-bench.py)  
Wrapper: [`local/scripts/run-alloy-scale-bench.sh`](../../scripts/run-alloy-scale-bench.sh)

```bash
# WSL — uses srl-local/alloy:network-dev, host network, GOMAXPROCS=1
bash local/scripts/run-alloy-scale-bench.sh --devices 100 --snmp-settle 90
bash local/scripts/run-alloy-scale-bench.sh --skip-snmp --eps-max 16000
```

Does **not** touch the colocated Clos. Planning numbers from the last run are in `report.md` and in the public guide [`docs/scalability.md`](https://github.com/Mesverrum/grafana-network-o11y-guide/blob/main/docs/scalability.md).
