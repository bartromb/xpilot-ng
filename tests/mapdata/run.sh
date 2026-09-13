#!/bin/sh
#
# Map data download and extraction, against a hostile local server.
#
#   run.sh FETCH_BINARY GOOD_PACKAGE
#
# FETCH_BINARY is tests/mapdata/fetch.c built against the client's mapdata.c,
# ideally with -fsanitize=address,undefined: several of these cases were memory
# errors before they were refusals, and a sanitizer is what tells the two
# apart. GOOD_PACKAGE is a real data package, e.g. lib/maps/ndh.xpd.
#
# Every case runs with its own empty HOME, which is where the client unpacks.

set -u

fetch=$1
good=$2
port=${MAPDATA_TEST_PORT:-18080}
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
failures=0

cleanup() {
    [ -n "${server_pid:-}" ] && kill "$server_pid" 2>/dev/null
    rm -rf -- "$work"
}
trap cleanup EXIT

python3 "$here/serve.py" "$port" "$good" > "$work/server.out" 2>&1 &
server_pid=$!
for _ in $(seq 1 50); do
    grep -q ready "$work/server.out" 2>/dev/null && break
    sleep 0.1
done
grep -q ready "$work/server.out" || { echo "test server did not start"; cat "$work/server.out"; exit 1; }

# case NAME URL EXPECT, where EXPECT is "ok" or "refused"
case_() {
    name=$1 url=$2 expect=$3
    home="$work/home-$name"
    mkdir -p -- "$home"

    out=$(HOME="$home" ASAN_OPTIONS=detect_leaks=0 "$fetch" "$url" 2>&1)
    rc=$?

    verdict=pass
    reason=""
    if printf '%s\n' "$out" | grep -q -e AddressSanitizer -e "runtime error"; then
        verdict=FAIL; reason="sanitizer reported a memory error"
    elif [ "$expect" = ok ] && [ "$rc" -ne 0 ]; then
        verdict=FAIL; reason="expected success, got exit $rc"
    elif [ "$expect" = refused ] && [ "$rc" -ne 1 ]; then
        verdict=FAIL; reason="expected a clean refusal (exit 1), got exit $rc"
    elif [ "$expect" = refused ] && [ -n "$(find "$home/.xpilot_data" -mindepth 1 -type d 2>/dev/null)" ]; then
        verdict=FAIL; reason="a refused package left a directory behind"
    elif [ "$expect" = refused ] && [ -n "$(find "$home/.xpilot_data" -name '*.xpd' 2>/dev/null)" ]; then
        verdict=FAIL; reason="a failed download left a package file behind"
    elif [ -n "$(find "$work" -name escaped.txt 2>/dev/null)" ]; then
        verdict=FAIL; reason="a file was written outside the package directory"
    fi

    printf '  %-4s %-10s %s\n' "$verdict" "$name" "$reason"
    if [ "$verdict" = FAIL ]; then
        failures=$((failures + 1))
        printf '%s\n' "$out" | tail -20 | sed 's/^/        /'
    fi
}

base="http://127.0.0.1:$port/maps"

case_ redirect   "$base/good.xpd"       ok
case_ tofile     "$base/tofile.xpd"     refused
case_ filedirect "file:///etc/passwd.xpd" refused
case_ notfound   "$base/missing.xpd"    refused
case_ huge       "$base/huge.xpd"       refused
case_ longname   "$base/longname.xpd"   refused
case_ dotdot     "$base/dotdot.xpd"     refused
case_ backslash  "$base/backslash.xpd"  refused
case_ bomb       "$base/bomb.xpd"       refused
case_ truncated  "$base/truncated.xpd"  refused

# The good package must also be reused on a second connect, not re-fetched.
home="$work/home-redirect"
if HOME="$home" "$fetch" "$base/good.xpd" 2>&1 | grep -q "already been downloaded"; then
    printf '  %-4s %-10s\n' pass reuse
else
    printf '  %-4s %-10s %s\n' FAIL reuse "second connect downloaded again"
    failures=$((failures + 1))
fi

if [ "$failures" -ne 0 ]; then
    echo "$failures map data case(s) failed"
    exit 1
fi
echo "all map data cases passed"
