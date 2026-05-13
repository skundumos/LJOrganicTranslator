# Bundled Noto fonts

Download the **Bold** variant of each script-specific Noto Sans font from
https://fonts.google.com/noto and drop them here:

```
NotoSans-Bold.ttf                    (fallback for Latin / Hinglish)
NotoSansDevanagari-Bold.ttf          (Hindi, Marathi)
NotoSansTamil-Bold.ttf               (Tamil)
NotoSansTelugu-Bold.ttf              (Telugu)
NotoSansKannada-Bold.ttf             (Kannada)
NotoSansMalayalam-Bold.ttf           (Malayalam)
NotoSansBengali-Bold.ttf             (Bengali)
NotoSansGujarati-Bold.ttf            (Gujarati)
NotoSansGurmukhi-Bold.ttf            (Punjabi)
```

The script-specific files include the conjunct GSUB tables — the generic
`NotoSans-Bold.ttf` does NOT and will render Devanagari/Tamil with broken
combining marks. Do not substitute.

Quick install on Linux/macOS:
```
curl -L -o NotoSansDevanagari-Bold.ttf \
  "https://github.com/notofonts/devanagari/raw/main/fonts/NotoSansDevanagari/full/ttf/NotoSansDevanagari-Bold.ttf"
```
Repeat with the matching `notofonts/<script>` repo for each language.
