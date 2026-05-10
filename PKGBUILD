pkgname=waytimer
pkgver=1.0.0
pkgrel=1
pkgdesc="Simple activity timer with fuzzel menu and waybar integration"
arch=('any')
url="https://github.com/filipeoliv02/waytimer"
license=('MIT')
depends=('python' 'fuzzel' 'waybar')
source=("$pkgname-$pkgver.tar.gz")
sha256sums=('SKIP')

package() {
    cd "$srcdir/$pkgname-$pkgver"
    install -Dm755 waytimer.py "$pkgdir/usr/bin/waytimer"
    install -Dm644 waybar-config.jsonc "$pkgdir/usr/share/waytimer/waybar-config.jsonc"
    install -Dm644 waybar-style.css "$pkgdir/usr/share/waytimer/waybar-style.css"
    install -Dm644 README.md "$pkgdir/usr/share/doc/waytimer/README.md"
}