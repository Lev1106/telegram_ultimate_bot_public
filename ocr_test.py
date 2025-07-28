from PIL import Image

import pytesseract

pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

print(pytesseract.image_to_string(Image.open('../photo_2025-07-25_19-59-40.jpg'), lang='rus+eng'))
