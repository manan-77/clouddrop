FROM node:24-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Static files plus a same-origin proxy to the API: no hostname is baked into the build.
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY nginx/security-headers.inc.template /etc/nginx/templates/security-headers.inc.template
COPY --from=build /app/dist/clouddrop-web/browser /usr/share/nginx/html
# The template reads this at start-up; the API service name inside the compose network.
ENV API_UPSTREAM=http://api:8000 CONNECT_SRC_EXTRA=https://*.amazonaws.com
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/nginx-health"]
