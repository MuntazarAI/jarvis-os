# JARVIS-OS Production Deployment

This directory contains all artifacts needed to deploy JARVIS-OS to Kubernetes.

## 📁 Structure

```
deploy/
├── Dockerfile              # Multi-stage production Docker image
├── health.py               # FastAPI health/readiness/metrics endpoints
├── metrics.py              # Prometheus metrics module
├── requirements.txt        # Python dependencies
└── k8s/
    ├── deployment.yaml     # Kubernetes Deployment
    ├── service.yaml        # Kubernetes Services (ClusterIP + Headless)
    ├── configmap.yaml      # Configuration (ConfigMap)
    ├── secret.yaml         # Secrets template (SealedSecrets ready)
    ├── servicemonitor.yaml # Prometheus ServiceMonitor + Alert Rules
    └── pvc.yaml            # PersistentVolumeClaims (optional)
```

## 🚀 Quick Start

### Prerequisites

- Kubernetes 1.24+
- Helm 3.x (optional, for Prometheus Operator)
- Container registry access
- `kubectl` configured

### 1. Build & Push Image

```bash
# Build
docker build -t your-registry/jarvis-os:v2.0.0 -f Dockerfile /tmp/jarvis-os

# Push
docker push your-registry/jarvis-os:v2.0.0
```

### 2. Update Image Reference

Edit `k8s/deployment.yaml`:
```yaml
image: your-registry/jarvis-os:v2.0.0
```

### 3. Create Namespace & Secrets

```bash
# Create namespace
kubectl create namespace jarvis

# Apply secrets (use SealedSecrets in production!)
kubectl apply -f k8s/secret.yaml -n jarvis
```

### 4. Deploy

```bash
# Apply all manifests
kubectl apply -f k8s/ -n jarvis

# Or individually:
kubectl apply -f k8s/configmap.yaml -n jarvis
kubectl apply -f k8s/deployment.yaml -n jarvis
kubectl apply -f k8s/service.yaml -n jarvis
kubectl apply -f k8s/servicemonitor.yaml -n jarvis
```

### 5. Verify

```bash
# Check pods
kubectl get pods -n jarvis -l app=jarvis-os

# Check logs
kubectl logs -n jarvis -l app=jarvis-os -f

# Check health
kubectl exec -n jarvis deployment/jarvis-os -- curl localhost:8080/health

# Check metrics
kubectl exec -n jarvis deployment/jarvis-os -- curl localhost:9090/metrics
```

## ⚙️ Configuration

### Environment Variables

All config via `k8s/configmap.yaml` and `k8s/secret.yaml`:

| Variable | Description | Default |
|----------|-------------|---------|
| `JARVIS_CONFIG_PATH` | Config file path | `/etc/jarvis/config.yaml` |
| `JARVIS_DATA_DIR` | Data directory | `/var/lib/jarvis` |
| `JARVIS_LOG_DIR` | Log directory | `/var/log/jarvis` |

### Key Config Sections (config.yaml)

- **server**: Host, port, workers, timeouts
- **logging**: Level, format, output
- **jarvis**: Stark agents, agent mesh, cognitive engine, world model, memory, OMNINET
- **foundation**: Model router, inference, benchmarks
- **perception**: Vision, audio, video, multimodal, sensor fusion
- **autonomy**: Systemd, resources, desktop, hardware
- **security**: Policy engine, secrets, network egress
- **observability**: Metrics, health, readiness, tracing

## 📊 Monitoring

### Prometheus Metrics

Available at `:9090/metrics`:

- **System**: CPU, memory, disk
- **JARVIS Core**: Status, uptime, subsystems
- **Agents**: Count, tasks, failures, duration
- **Task Queue**: Depth, enqueued, dequeued, failed
- **Tools**: Calls, duration, success/failure
- **Inference**: Requests, duration, tokens
- **HTTP**: Requests, duration, status codes
- **Database**: Connections, query duration

### Grafana Dashboard

Import `grafana-dashboard.json` (not included, create from metrics above).

### Key Alerts (servicemonitor.yaml)

- `JarvisOSDown` - Instance down > 2min
- `JarvisOSHighMemory` - > 85% memory
- `JarvisOSHighCPU` - > 85% CPU
- `JarvisOSAgentFailure` - Failure rate > 10%
- `JarvisOSTaskQueueBacklog` - Queue > 1000
- `JarvisOSDiskSpace` - Disk > 85%

## 🔐 Security

### Non-Root Container

- Runs as UID/GID 1000
- Read-only root filesystem
- Dropped capabilities
- Seccomp profile: RuntimeDefault

### Network Policies

```yaml
# Example: restrict egress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: jarvis-os-egress
  namespace: jarvis
spec:
  podSelector:
    matchLabels:
      app: jarvis-os
  policyTypes:
    - Egress
  egress:
    - to:
      - namespaceSelector:
          matchLabels:
            name: monitoring
      ports:
        - protocol: TCP
          port: 9090
    - to: []
      ports:
        - protocol: TCP
          port: 443  # HTTPS for external APIs
        - protocol: TCP
          port: 53   # DNS
```

### SealedSecrets

For production, encrypt secrets:

```bash
# Install SealedSecrets controller
kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/latest/download/controller.yaml

# Seal secret
kubeseal --format=yaml < k8s/secret.yaml > k8s/secret-sealed.yaml

# Apply sealed secret
kubectl apply -f k8s/secret-sealed.yaml
```

## 📦 Persistent Storage

### PVCs (create separately)

```yaml
# k8s/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: jarvis-data
  namespace: jarvis
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: fast-ssd
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: jarvis-logs
  namespace: jarvis
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
  storageClassName: standard
```

## 🔄 Rolling Updates

Deployment uses `RollingUpdate` strategy:
- `maxSurge: 1` - One extra pod during update
- `maxUnavailable: 0` - Zero downtime

```bash
# Update image
kubectl set image deployment/jarvis-os jarvis-os=your-registry/jarvis-os:v2.0.1 -n jarvis

# Rollback
kubectl rollout undo deployment/jarvis-os -n jarvis

# Check status
kubectl rollout status deployment/jarvis-os -n jarvis
```

## 🧪 Testing

### Local Development

```bash
# Run health server locally
cd /tmp/jarvis-os
python -m deploy.health

# Test endpoints
curl http://localhost:8080/health
curl http://localhost:8080/ready
curl http://localhost:9090/metrics
```

### Integration Tests

```bash
# Run in test namespace
kubectl create namespace jarvis-test
kubectl apply -f k8s/ -n jarvis-test

# Run tests
kubectl run -n jarvis-test --rm -i --restart=Never test-pod \
  --image=curlimages/curl -- \
  curl -f http://jarvis-os.jarvis-test:8080/health
```

## 📝 Requirements

```
fastapi>=0.100.0
uvicorn>=0.23.0
psutil>=5.9.0
pydantic>=2.0.0
prometheus-client>=0.17.0
```

Install: `pip install -r requirements.txt`

## 🆘 Troubleshooting

| Issue | Solution |
|-------|----------|
| Pods stuck in `Pending` | Check PVC binding, node resources, taints |
| Health check failing | Check logs, verify `/health` endpoint |
| Metrics not scraping | Verify ServiceMonitor, Prometheus RBAC |
| OOMKilled | Increase memory limit, check for leaks |
| Config not loading | Verify ConfigMap mount, YAML syntax |

## 📚 References

- [Kubernetes Deployment Best Practices](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
- [Prometheus Monitoring](https://prometheus.io/docs/introduction/overview/)
- [FastAPI Health Checks](https://fastapi.tiangolo.com/tutorial/testing/)
- [SealedSecrets](https://github.com/bitnami-labs/sealed-secrets)