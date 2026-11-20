FROM node:24-bookworm-slim
WORKDIR /app
COPY --chown=1000:1000 config.mjs github.mjs feed.mjs server.mjs ./
COPY --chown=1000:1000 accounts.mjs account-http.mjs bootstrap.mjs password-blocklist.sha256 password-blocklist.LICENSE ./
COPY --chown=1000:1000 public/ ./public/
ENV DAF_BIND=0.0.0.0 DAF_PORT=8080
USER 1000:1000
EXPOSE 8080
CMD ["node", "server.mjs"]
