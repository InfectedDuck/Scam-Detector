# The web app. Build from the repository root, not from web/:
#   docker build -f web/Dockerfile .
# docker-compose.yml does exactly that. The root context is needed because
# the app reads the backend's i18n and playbook YAML, and the share, library
# and Open Graph pages are prerendered from them at build time.
#
# Dockerfile.dockerignore beside this file replaces the root .dockerignore
# for this build, since the root one excludes web/ for the Python image.

FROM node:24-alpine AS build
WORKDIR /app

# Dependency layer first, so a code change does not reinstall the world.
COPY web/package.json web/package-lock.json ./
RUN npm ci

# The two backend directories the app reads, at the paths the ENV below names.
COPY src/saqbol/i18n ./backend/i18n
COPY src/saqbol/playbooks/data ./backend/playbooks

COPY web ./
ENV SAQBOL_I18N_DIR=/app/backend/i18n \
    SAQBOL_PLAYBOOKS_DIR=/app/backend/playbooks \
    NEXT_TELEMETRY_DISABLED=1
# Prerendering must not call the API: SAQBOL_API_BASE is deliberately unset here.
RUN npm run build && npm prune --omit=dev

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production \
    SAQBOL_I18N_DIR=/app/backend/i18n \
    SAQBOL_PLAYBOOKS_DIR=/app/backend/playbooks \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN addgroup -S saqbol && adduser -S -G saqbol saqbol

COPY --from=build --chown=saqbol:saqbol /app/package.json /app/package-lock.json ./
COPY --from=build --chown=saqbol:saqbol /app/node_modules ./node_modules
COPY --from=build --chown=saqbol:saqbol /app/.next ./.next
COPY --from=build --chown=saqbol:saqbol /app/next.config.ts ./
COPY --from=build --chown=saqbol:saqbol /app/app/og/fonts ./app/og/fonts
COPY --from=build --chown=saqbol:saqbol /app/backend ./backend

USER saqbol
EXPOSE 3000
CMD ["npm", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
