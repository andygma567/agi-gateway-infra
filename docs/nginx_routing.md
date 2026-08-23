# How nginx hostname routing works

Both `langfuse.test` and `litellm.test` resolve to the **same IP** (your VM). DNS does no routing here — every request arrives at nginx on port 80.

What distinguishes the requests is the HTTP `Host` header: the browser sends `Host: langfuse.test` or `Host: litellm.test` based on the URL you typed. nginx matches that header against each `server` block's `server_name` and picks a winner.

```nginx
server {
    listen 80;
    server_name langfuse.test;   # <-- match on Host header

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;   # pass the original name to the app
        ...
    }
}
```

`proxy_set_header Host $host` matters so Langfuse builds links with `langfuse.test` instead of `127.0.0.1`. That pairs with `NEXTAUTH_URL=http://langfuse.test` in [`roles/langfuse/files/langfuse.env`](../roles/langfuse/files/langfuse.env).

`proxy_buffering off` on the LiteLLM block lets LLM tokens stream through as they arrive. With buffering on, nginx would collect the whole response first.

## Why `.test`?

`.test` is a reserved domain suffix (like `.com`), not related to automated testing. macOS routes `.local` lookups to Bonjour/mDNS instead of `/etc/hosts`, so names like `langfuse.local` can appear to be ignored. Changing the suffix is a find-and-replace in [`roles/nginx_gateway/files/gateway.conf`](../roles/nginx_gateway/files/gateway.conf) and [`roles/langfuse/files/langfuse.env`](../roles/langfuse/files/langfuse.env).

## Optional next steps

- A `default_server` catch-all that rejects unknown Host values
- WebSocket `Upgrade` / `Connection` headers if you add a service that needs them
- TLS with Let's Encrypt once you have a real domain
