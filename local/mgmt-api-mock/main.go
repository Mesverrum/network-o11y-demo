// mgmt-api-mock — export SR Linux management API capability catalog over OTLP
// metrics. APIs not enabled in the local lab (NETCONF, JSON-RPC, gNOI, gRIBI)
// still appear with mock=true; sample payloads live under fixtures/srl-mock/.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/metric"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	semconv "go.opentelemetry.io/otel/semconv/v1.24.0"
)

type catalog struct {
	Platform    string `json:"platform"`
	Release     string `json:"release"`
	Description string `json:"description"`
	APIs        []api  `json:"apis"`
}

type api struct {
	Name            string `json:"name"`
	Transport       string `json:"transport"`
	Port            int    `json:"port"`
	Path            string `json:"path"`
	NetworkInstance string `json:"network_instance"`
	EnabledInLab    bool   `json:"enabled_in_lab"`
	LabCollector    string `json:"lab_collector"`
	Mock            bool   `json:"mock"`
	SampleFixture   string `json:"sample_fixture"`
	DocsURL         string `json:"docs_url"`
}

type device struct {
	Name string
	IP   string
}

func main() {
	catalogPath := flag.String("catalog", "fixtures/srl-mgmt-api-catalog.json", "API catalog JSON")
	otlp := flag.String("otlp", envOr("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317"), "OTLP gRPC endpoint")
	tester := flag.String("tester-id", envOr("LAB_TESTER_ID", "network-lab"), "tester_id label")
	devicesFlag := flag.String("devices", "", "comma-separated name=ip (e.g. spine1=172.20.20.6,leaf1=...)")
	root := flag.String("root", ".", "repo local/ root for fixture paths")
	flag.Parse()

	devices, err := parseDevices(*devicesFlag)
	if err != nil {
		log.Fatal(err)
	}
	if len(devices) == 0 {
		log.Fatal("no devices — pass --devices spine1=ip,leaf1=ip,leaf2=ip")
	}

	cat, err := loadCatalog(filepath.Join(*root, *catalogPath))
	if err != nil {
		log.Fatalf("catalog: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	shutdown, err := initOTel(ctx, *otlp, *tester, cat)
	if err != nil {
		log.Fatalf("otel: %v", err)
	}
	defer func() {
		c, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = shutdown(c)
	}()

	if err := emitCapabilities(cat, devices, *tester, *root); err != nil {
		log.Fatalf("metrics: %v", err)
	}

	time.Sleep(3 * time.Second)
	log.Printf("exported srl_mgmt_api_capability_info for %d devices × %d APIs", len(devices), len(cat.APIs))
}

func envOr(k, def string) string {
	if v := strings.TrimSpace(os.Getenv(k)); v != "" {
		return v
	}
	return def
}

func parseDevices(raw string) ([]device, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil, nil
	}
	var out []device
	for _, part := range strings.Split(raw, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		name, ip, ok := strings.Cut(part, "=")
		if !ok || name == "" || ip == "" {
			return nil, fmt.Errorf("invalid device %q — want name=ip", part)
		}
		out = append(out, device{Name: strings.TrimSpace(name), IP: strings.TrimSpace(ip)})
	}
	return out, nil
}

func loadCatalog(path string) (*catalog, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var c catalog
	if err := json.Unmarshal(b, &c); err != nil {
		return nil, err
	}
	return &c, nil
}

func initOTel(ctx context.Context, endpoint, testerID string, cat *catalog) (func(context.Context) error, error) {
	res := resource.NewWithAttributes(
		semconv.SchemaURL,
		semconv.ServiceName("srl-mgmt-api-mock"),
		attribute.String("tester_id", testerID),
		attribute.String("platform", cat.Platform),
		attribute.String("platform.release", cat.Release),
	)

	mexp, err := otlpmetricgrpc.New(ctx,
		otlpmetricgrpc.WithEndpoint(endpoint),
		otlpmetricgrpc.WithInsecure(),
	)
	if err != nil {
		return nil, err
	}
	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithResource(res),
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(mexp, sdkmetric.WithInterval(1*time.Second))),
	)
	otel.SetMeterProvider(mp)

	return mp.Shutdown, nil
}

func emitCapabilities(cat *catalog, devices []device, testerID, root string) error {
	meter := otel.Meter("srl-mgmt-api-mock")
	tester := attribute.String("tester_id", testerID)
	platform := attribute.String("platform", cat.Platform)
	release := attribute.String("platform_release", cat.Release)

	type row struct {
		attrs []attribute.KeyValue
	}
	var rows []row

	for _, d := range devices {
		devName := attribute.String("device_name", d.Name)
		mgmtIP := attribute.String("mgmt_ip", d.IP)
		for _, api := range cat.APIs {
			enabled := "false"
			if api.EnabledInLab {
				enabled = "true"
			}
			mock := "false"
			fixturePresent := "false"
			if api.Mock {
				mock = "true"
				if api.SampleFixture != "" {
					p := filepath.Join(root, filepath.FromSlash(api.SampleFixture))
					if _, err := os.Stat(p); err == nil {
						fixturePresent = "true"
					}
				}
			}
			rows = append(rows, row{attrs: []attribute.KeyValue{
				tester, platform, release, devName, mgmtIP,
				attribute.String("api", api.Name),
				attribute.String("transport", api.Transport),
				attribute.String("port", fmt.Sprintf("%d", api.Port)),
				attribute.String("path", api.Path),
				attribute.String("network_instance", api.NetworkInstance),
				attribute.String("enabled_in_lab", enabled),
				attribute.String("mock", mock),
				attribute.String("fixture_present", fixturePresent),
				attribute.String("lab_collector", api.LabCollector),
				attribute.String("docs_url", api.DocsURL),
				attribute.String("sample_fixture", api.SampleFixture),
			}})
		}
	}

	_, err := meter.Int64ObservableGauge("srl.mgmt.api.capability.info",
		metric.WithDescription("SR Linux northbound management API catalog (live + mock) per device"),
		metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
			for _, r := range rows {
				o.Observe(1, metric.WithAttributes(r.attrs...))
			}
			return nil
		}),
	)
	return err
}
