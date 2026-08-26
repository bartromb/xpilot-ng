# XPilot NG dedicated server.
#
#   docker build -f packaging/Dockerfile -t xpilot-ng-server .
#   docker run --rm -p 15345:15345/udp -p 15346-15400:15346-15400/udp \
#       xpilot-ng-server
#
# Note both port mappings. The server serves the game from a fresh UDP port
# per connection rather than from 15345, so publishing only 15345 gives a
# login that succeeds and then goes silent. The range below is pinned with
# -clientPortStart/-clientPortEnd precisely so it can be published. See
# docs/protocol.md.

# ---- build ----------------------------------------------------------------
FROM ubuntu:24.04 AS build

# Only what the server needs. The clients, and therefore SDL, X11 and OpenGL,
# are deliberately not built here.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake \
        libexpat1-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . .

RUN cmake -B build -S . \
        -DCMAKE_BUILD_TYPE=RelWithDebInfo \
        -DXPILOT_X11_CLIENT=OFF \
        -DXPILOT_SDL_CLIENT=OFF \
        -DXPILOT_REPLAY=OFF \
        -DXPILOT_MAPEDIT=OFF \
    && cmake --build build -j"$(nproc)" \
    && cmake --install build

# ---- runtime --------------------------------------------------------------
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --no-create-home --shell /usr/sbin/nologin xpilot

COPY --from=build /usr/local/bin/xpilot-ng-server /usr/local/bin/
COPY --from=build /usr/local/share/xpilot-ng /usr/local/share/xpilot-ng

USER xpilot

EXPOSE 15345/udp
EXPOSE 15346-15400/udp

# -noQuit and -idleRun keep the server alive when empty; without them it exits
# as soon as the last human leaves, which in a container reads as a crash loop.
ENTRYPOINT ["/usr/local/bin/xpilot-ng-server"]
CMD ["-map", "/usr/local/share/xpilot-ng/maps/blood-music.xp2", \
     "-port", "15345", \
     "-clientPortStart", "15346", \
     "-clientPortEnd", "15400", \
     "-noQuit", "-idleRun"]
