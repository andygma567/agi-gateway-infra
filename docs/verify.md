# Manual checks

After `ansible-playbook site.yml` finishes, Langfuse still needs a couple of minutes for migrations on first boot.

## One-time: hosts file

On your laptop (replace `203.0.113.10` with your VM IP):

```bash
echo "203.0.113.10 langfuse.test litellm.test" | sudo tee -a /etc/hosts
```

## Health checks

```bash
curl -i http://langfuse.test/api/public/health      # expect 200
curl -i http://litellm.test/health/liveliness       # expect 200
```

## Headless init

```bash
curl -su 'pk-lf-local-dev-public-key:sk-lf-local-dev-secret-key' \
  http://langfuse.test/api/public/projects
```

## UIs

- Langfuse: http://langfuse.test — log in as `local@langfuse.com` / `password`
- LiteLLM: http://litellm.test/ui — log in as `admin` / `sk-local-dev-master-key`

## Debugging

Test nginx routing without `/etc/hosts` (sets the Host header by hand):

```bash
curl -i -H 'Host: langfuse.test' http://203.0.113.10/api/public/health
```

Bypass nginx and hit the app port directly:

```bash
curl -i http://203.0.113.10:3000/api/public/health
curl -i http://203.0.113.10:4000/health/liveliness
```

On the VM:

```bash
cd /opt/langfuse && docker compose ps
docker compose logs -f langfuse-web

cd /opt/litellm && docker compose ps
docker compose logs -f

nginx -t

# If a compose file changed and something broke:
ls /opt/langfuse/docker-compose.yml.*
diff /opt/langfuse/docker-compose.yml.*~ /opt/langfuse/docker-compose.yml
```
