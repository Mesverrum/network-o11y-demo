// Minimal Clos join demo: HTTP client (client1) ↔ server (client2) over EVPN,
// with OpenTelemetry traces exported to Alloy for 5-tuple join vs softflowd.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.24.0"
	"go.opentelemetry.io/otel/trace"
)

func main() {
	role := flag.String("role", envOr("JOIN_ROLE", ""), "server|client")
	listen := flag.String("listen", envOr("JOIN_LISTEN", ":8080"), "server listen addr")
	peer := flag.String("peer", envOr("JOIN_PEER", "http://172.17.0.2:8080"), "client target base URL")
	interval := flag.Duration("interval", envDuration("JOIN_INTERVAL", 2*time.Second), "client request interval")
	otlp := flag.String("otlp", envOr("OTEL_EXPORTER_OTLP_ENDPOINT", "alloy:4317"), "OTLP gRPC endpoint (host:port)")
	service := flag.String("service", envOr("OTEL_SERVICE_NAME", "clos-join-demo"), "OTel service.name")
	flag.Parse()

	if *role != "server" && *role != "client" {
		log.Fatal("usage: join-app -role=server|client")
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	host, _ := os.Hostname()
	shutdown, err := initOTel(ctx, *otlp, *service, host, *role)
	if err != nil {
		log.Fatalf("otel init: %v", err)
	}
	defer func() {
		c, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = shutdown(c)
	}()

	if err := registerEntityMetrics(*service, host, *role); err != nil {
		log.Fatalf("entity metrics: %v", err)
	}
	// Emit identity prove/disprove datasets once (client); avoids duplicate series.
	if *role == "client" {
		if err := registerIdentityDemoMetrics(); err != nil {
			log.Fatalf("identity demo metrics: %v", err)
		}
	}

	switch *role {
	case "server":
		if err := runServer(ctx, *listen, host); err != nil {
			log.Fatal(err)
		}
	case "client":
		if err := runClient(ctx, *peer, *interval, host); err != nil {
			log.Fatal(err)
		}
	}
}

func runServer(ctx context.Context, listen, host string) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok\n"))
	})
	mux.Handle("/work", otelhttp.NewHandler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		span := trace.SpanFromContext(r.Context())
		peerHost, peerPort := splitHostPort(r.RemoteAddr)
		span.SetAttributes(
			attribute.String("network.transport", "tcp"),
			attribute.String("network.type", "ipv4"),
			attribute.String("network.peer.address", peerHost),
			attribute.Int("network.peer.port", peerPort),
			attribute.String("server.address", localIPv4Hint()),
			attribute.Int("server.port", listenPort(listen)),
			attribute.String("clos.role", "server"),
			attribute.String("clos.host", host),
		)
		time.Sleep(15 * time.Millisecond) // tiny, stable latency for demo
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"ok":      true,
			"host":    host,
			"peer":    r.RemoteAddr,
			"message": "clos-join-demo",
		})
	}), "work"))

	srv := &http.Server{
		Addr:              listen,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		<-ctx.Done()
		c, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		_ = srv.Shutdown(c)
	}()

	log.Printf("server listening on %s (host=%s)", listen, host)
	err := srv.ListenAndServe()
	if err == http.ErrServerClosed {
		return nil
	}
	return err
}

func runClient(ctx context.Context, peerURL string, interval time.Duration, host string) error {
	peerURL = strings.TrimRight(peerURL, "/")
	target := peerURL + "/work"
	peerHost, peerPort := hostPortFromURL(peerURL)

	client := &http.Client{
		Timeout: 5 * time.Second,
		Transport: otelhttp.NewTransport(http.DefaultTransport,
			otelhttp.WithSpanNameFormatter(func(_ string, r *http.Request) string {
				return "GET " + r.URL.Path
			}),
		),
	}

	log.Printf("client targeting %s every %s (host=%s)", target, interval, host)
	t := time.NewTicker(interval)
	defer t.Stop()

	// Fire immediately, then on ticker.
	for {
		if err := doRequest(ctx, client, target, peerHost, peerPort, host); err != nil {
			log.Printf("request error: %v", err)
		}
		select {
		case <-ctx.Done():
			return nil
		case <-t.C:
		}
	}
}

func doRequest(ctx context.Context, client *http.Client, target, peerHost string, peerPort int, host string) error {
	ctx, span := otel.Tracer("clos-join-demo").Start(ctx, "clos.join.request",
		trace.WithSpanKind(trace.SpanKindClient),
		trace.WithAttributes(
			attribute.String("network.transport", "tcp"),
			attribute.String("network.type", "ipv4"),
			attribute.String("network.peer.address", peerHost),
			attribute.Int("network.peer.port", peerPort),
			attribute.String("server.address", peerHost),
			attribute.Int("server.port", peerPort),
			attribute.String("clos.role", "client"),
			attribute.String("clos.host", host),
			attribute.String("clos.local.address", localIPv4Hint()),
		),
	)
	defer span.End()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		span.RecordError(err)
		return err
	}

	start := time.Now()
	resp, err := client.Do(req)
	if err != nil {
		span.RecordError(err)
		return err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
	span.SetAttributes(attribute.Int("http.response.status_code", resp.StatusCode))

	log.Printf("GET %s -> %d (%s) %s", target, resp.StatusCode, time.Since(start).Round(time.Millisecond), strings.TrimSpace(string(body)))
	if resp.StatusCode >= 300 {
		return fmt.Errorf("status %d", resp.StatusCode)
	}
	return nil
}

func initOTel(ctx context.Context, endpoint, service, host, role string) (func(context.Context) error, error) {
	endpoint = strings.TrimPrefix(endpoint, "http://")
	endpoint = strings.TrimPrefix(endpoint, "https://")
	endpoint = strings.TrimSuffix(endpoint, "/")

	res, err := resource.New(ctx,
		resource.WithAttributes(
			semconv.ServiceName(service),
			semconv.ServiceInstanceID(host+"-"+role),
			semconv.DeploymentEnvironment(testerID()),
			attribute.String("clos.role", role),
			attribute.String("host.name", host),
		),
	)
	if err != nil {
		return nil, err
	}

	traceExp, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint(endpoint),
		otlptracegrpc.WithInsecure(),
	)
	if err != nil {
		return nil, err
	}
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(traceExp),
		sdktrace.WithResource(res),
		sdktrace.WithSampler(sdktrace.AlwaysSample()),
	)
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.TraceContext{})

	metricExp, err := otlpmetricgrpc.New(ctx,
		otlpmetricgrpc.WithEndpoint(endpoint),
		otlpmetricgrpc.WithInsecure(),
	)
	if err != nil {
		return nil, err
	}
	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(metricExp, sdkmetric.WithInterval(15*time.Second))),
		sdkmetric.WithResource(res),
	)
	otel.SetMeterProvider(mp)

	return func(ctx context.Context) error {
		err1 := tp.Shutdown(ctx)
		err2 := mp.Shutdown(ctx)
		if err1 != nil {
			return err1
		}
		return err2
	}, nil
}

// registerEntityMetrics exports a tiny entity overlay for the Clos nodeGraph:
// service clos-join-demo —runs_on→ client1/client2 —attached→ leaf1/leaf2.
func registerEntityMetrics(service, host, role string) error {
	meter := otel.Meter("clos-join-demo")
	tester := attribute.String("tester_id", testerID())

	entities := [][]attribute.KeyValue{
		{tester, attribute.String("id", service), attribute.String("kind", "service"), attribute.String("title", service)},
		{tester, attribute.String("id", "client1"), attribute.String("kind", "host"), attribute.String("title", "client1")},
		{tester, attribute.String("id", "client2"), attribute.String("kind", "host"), attribute.String("title", "client2")},
	}
	// Highlight which host this process runs on in subTitle-ish detail.
	entities = append(entities,
		[]attribute.KeyValue{
			tester,
			attribute.String("id", host),
			attribute.String("kind", "host"),
			attribute.String("title", host),
			attribute.String("detail", "join-app-"+role),
		},
	)

	edges := [][]attribute.KeyValue{
		{
			tester,
			attribute.String("id", "runs_on-client1"),
			attribute.String("src", service),
			attribute.String("dst", "client1"),
			attribute.String("kind", "runs_on"),
		},
		{
			tester,
			attribute.String("id", "runs_on-client2"),
			attribute.String("src", service),
			attribute.String("dst", "client2"),
			attribute.String("kind", "runs_on"),
		},
		{
			tester,
			attribute.String("id", "attached-client1-leaf1"),
			attribute.String("src", "client1"),
			attribute.String("dst", "leaf1"),
			attribute.String("kind", "attached"),
		},
		{
			tester,
			attribute.String("id", "attached-client2-leaf2"),
			attribute.String("src", "client2"),
			attribute.String("dst", "leaf2"),
			attribute.String("kind", "attached"),
		},
	}

	_, err := meter.Int64ObservableGauge("clos.join.entity.info",
		metric.WithDescription("Join-demo entity nodes for Clos subway overlay (service/host)"),
		metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
			for _, attrs := range entities {
				o.Observe(1, metric.WithAttributes(attrs...))
			}
			return nil
		}),
	)
	if err != nil {
		return err
	}

	_, err = meter.Int64ObservableGauge("clos.join.edge.info",
		metric.WithDescription("Join-demo entity edges (runs_on / attached) for Clos subway overlay"),
		metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
			for _, attrs := range edges {
				o.Observe(1, metric.WithAttributes(attrs...))
			}
			return nil
		}),
	)
	return err
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func testerID() string {
	return envOr("LAB_TESTER_ID", "network-lab")
}

func envDuration(k string, def time.Duration) time.Duration {
	v := os.Getenv(k)
	if v == "" {
		return def
	}
	d, err := time.ParseDuration(v)
	if err != nil {
		return def
	}
	return d
}

func listenPort(listen string) int {
	_, p, err := net.SplitHostPort(listen)
	if err != nil {
		// ":8080" form
		if strings.HasPrefix(listen, ":") {
			n, _ := strconv.Atoi(strings.TrimPrefix(listen, ":"))
			return n
		}
		return 8080
	}
	n, _ := strconv.Atoi(p)
	return n
}

func splitHostPort(addr string) (string, int) {
	h, p, err := net.SplitHostPort(addr)
	if err != nil {
		return addr, 0
	}
	n, _ := strconv.Atoi(p)
	return h, n
}

func hostPortFromURL(raw string) (string, int) {
	raw = strings.TrimPrefix(raw, "http://")
	raw = strings.TrimPrefix(raw, "https://")
	if i := strings.IndexByte(raw, '/'); i >= 0 {
		raw = raw[:i]
	}
	h, p := splitHostPort(raw)
	if p == 0 {
		return h, 80
	}
	return h, p
}

func localIPv4Hint() string {
	// Prefer EVPN client address if present on eth1-ish interfaces.
	ifaces, err := net.Interfaces()
	if err != nil {
		return ""
	}
	for _, iface := range ifaces {
		addrs, _ := iface.Addrs()
		for _, a := range addrs {
			ipnet, ok := a.(*net.IPNet)
			if !ok || ipnet.IP.To4() == nil || ipnet.IP.IsLoopback() {
				continue
			}
			ip := ipnet.IP.String()
			if strings.HasPrefix(ip, "172.17.0.") {
				return ip
			}
		}
	}
	return ""
}
