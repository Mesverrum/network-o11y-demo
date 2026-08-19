# Copied into netbox-docker on colocated bring-up; secrets filled by bringup script.
PLUGINS = ["netbox_diode_plugin"]

PLUGINS_CONFIG = {
    "netbox_diode_plugin": {
        # Diode is published on the Docker host (:8080). NetBox runs in bridge
        # networking, so use the bridge gateway — not 127.0.0.1.
        "diode_target_override": "grpc://172.17.0.1:8080/diode",
        "diode_username": "diode",
        "netbox_to_diode_client_secret": "PLACEHOLDER_NETBOX_TO_DIODE_SECRET",
    },
}
