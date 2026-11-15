#!/usr/bin/env bash
set -eo pipefail

profile=${1:?Missing build profile}
extra_packages=()
case "$profile" in
  base) ;;
  custom)
    while IFS= read -r package; do
      extra_packages+=("$package")
    done < <(printf '%s\n' "${CUSTOM_PACKAGES:-}" | tr '[:space:]' '\n' | sed '/^$/d' | sort -u)
    if (( ${#extra_packages[@]} == 0 )); then
      echo 'Provide at least one package name for the custom firmware.' >&2
      exit 1
    fi
    for package in "${extra_packages[@]}"; do
      if [[ ! "$package" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ ]]; then
        echo 'Invalid package name. Enter names only, without version constraints or file paths.' >&2
        exit 1
      fi
    done
    ;;
  *)
    echo "Unknown build profile: $profile" >&2
    exit 1
    ;;
esac

cd source
test "$(git rev-parse HEAD)" = "${SOURCE_SHA:?Missing OpenWrt source SHA}"

# These are unused preinstalled SDKs on this disposable hosted runner.
sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  build-essential clang flex bison g++ gawk gcc-multilib g++-multilib \
  gettext git libncurses-dev libssl-dev python3 python3-setuptools \
  python3-pyelftools rsync swig unzip zlib1g-dev file wget curl \
  ca-certificates bzip2 xz-utils zstd patch time \
  libelf-dev libzstd-dev liblz4-dev
df -h .
free -h

# Give the pinned source the same timestamps on each runner so OpenWrt can
# check its build stamps and reuse tools or build new ones as needed.
source_timestamp=$(git show -s --format=%ct HEAD)
git ls-files -z tools toolchain | xargs -0 -r touch -h -d "@$source_timestamp" --

cp ../configs/feeds.conf feeds.conf
./scripts/feeds update -a
./scripts/feeds install -a
cp ../configs/mt5000.config .config
symbols=(
  TARGET_mediatek_filogic_DEVICE_glinet_gl-mt5000
  PACKAGE_luci-ssl PACKAGE_kmod-wireguard PACKAGE_kmod-usb3
  PACKAGE_kmod-inet-diag PACKAGE_kmod-tun
)
for package in "${extra_packages[@]}"; do
  symbol="PACKAGE_${package}"
  symbols+=("$symbol")
  if ! grep -Fxq "CONFIG_${symbol}=y" .config; then
    printf 'CONFIG_%s=y\n' "$symbol" >> .config
  fi
done

make defconfig
for symbol in "${symbols[@]}"; do
  if ! grep -Fxq "CONFIG_${symbol}=y" .config; then
    echo "CONFIG_${symbol} could not be enabled for the selected target and feeds." >&2
    exit 1
  fi
done
./scripts/diffconfig.sh > config.seed
./scripts/feeds list -s > feeds.buildinfo
git rev-parse HEAD > source.commit
