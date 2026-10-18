# syntax=docker/dockerfile:1
#
# Build context is the repository root (the type-check includes shared/*.json fixtures):
#   docker build -f frontend/Dockerfile .
#
# Stage 1 builds the SPA. Stage 2 is nginx (unprivileged: runs as uid 101, listens on 8080/8443) serving the build and
# proxying /api and /ws to the backend. No Node, source or build tooling reaches the final image.

FROM node:26-alpine AS build
WORKDIR /repo
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci
COPY shared shared
COPY frontend frontend
RUN cd frontend && npm run build

FROM nginxinc/nginx-unprivileged:1.28-alpine AS web
COPY infrastructure/nginx/conf.d/ /etc/nginx/conf.d/
COPY infrastructure/nginx/snippets/ /etc/nginx/snippets/
COPY --from=build /repo/frontend/dist /usr/share/nginx/html
EXPOSE 8080 8443
