FROM node:22-alpine AS build

WORKDIR /app

COPY apps/web/package.json ./
RUN corepack enable && pnpm install

COPY apps/web/ ./
RUN pnpm run build

FROM nginx:1.27-alpine

COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

