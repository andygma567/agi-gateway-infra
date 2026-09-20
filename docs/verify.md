# Manual checks

After `ansible-playbook site.yml` finishes, LiteLLM should answer health checks immediately.

## One-time: hosts file

On your laptop (replace `203.0.113.10` with your VM IP):

```bash
echo "203.0.113.10 litellm.test" | sudo tee -a /etc/hosts
```

## Health checks

```bash
curl -i http://litellm.test/health/liveliness       # expect 200
```

## UI

- LiteLLM: http://litellm.test/ui — log in as `admin` / `sk-local-dev-master-key`

## Debugging

Test nginx routing without `/etc/hosts` (sets the Host header by hand):

```bash
curl -i -H 'Host: litellm.test' http://203.0.113.10/health/liveliness
```

Bypass nginx and hit the app port directly:

```bash
curl -i http://203.0.113.10:4000/health/liveliness
```

On the VM:

```bash
cd /opt/litellm && docker compose ps
docker compose logs -f

nginx -t

# If a compose file changed and something broke:
ls /opt/litellm/docker-compose.yml.*
diff /opt/litellm/docker-compose.yml.*~ /opt/litellm/docker-compose.yml
```
