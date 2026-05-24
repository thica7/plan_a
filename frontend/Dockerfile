FROM node:20-alpine AS build

WORKDIR /app
COPY frontend/package.json ./
RUN corepack enable && pnpm install
COPY frontend/ ./
RUN pnpm build

FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

