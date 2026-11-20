FROM node:24-bookworm-slim
WORKDIR /app
COPY config.mjs github.mjs feed.mjs server.mjs ./
COPY public/ ./public/
ENV DAF_BIND=0.0.0.0 DAF_PORT=8080
USER 1000:1000
EXPOSE 8080
CMD ["node", "server.mjs"]
