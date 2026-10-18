
import qrcode

url = "https://enlightenedscholar777-dev.github.io/The-Argonauts-Hackathon/"

qr = qrcode.QRCode(
    version=None,
    error_correction=qrcode.constants.ERROR_CORRECT_H,
    box_size=12,
    border=4,
)

qr.add_data(url)
qr.make(fit=True)

img = qr.make_image(
    fill_color="#0B1F33",
    back_color="white",
)

img.save("harbor_maester_qr.png")

print("QR code saved as harbor_maester_qr.png")
print(f"Website: {url}")
