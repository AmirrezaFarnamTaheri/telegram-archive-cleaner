FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8789
ENV HOST=0.0.0.0
COPY relay/common.mjs ./relay/common.mjs
COPY relay/github/worker.mjs ./relay/github/worker.mjs
USER node
EXPOSE 8789
CMD ["node", "relay/github/worker.mjs"]
