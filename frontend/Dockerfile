FROM node:20-alpine AS build

WORKDIR /app
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org/
ENV NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY} \
    COREPACK_NPM_REGISTRY=${NPM_CONFIG_REGISTRY}

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
