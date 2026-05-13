export type Language = {
  code: string;
  display_name: string;
  native_name: string;
  bcp47: string;
};

export const LANGUAGES: Language[] = [
  { code: "hi", display_name: "Hindi", native_name: "हिन्दी", bcp47: "hi-IN" },
  { code: "hinglish", display_name: "Hinglish", native_name: "Hinglish", bcp47: "en-IN" },
  { code: "ta", display_name: "Tamil", native_name: "தமிழ்", bcp47: "ta-IN" },
  { code: "te", display_name: "Telugu", native_name: "తెలుగు", bcp47: "te-IN" },
  { code: "kn", display_name: "Kannada", native_name: "ಕನ್ನಡ", bcp47: "kn-IN" },
  { code: "ml", display_name: "Malayalam", native_name: "മലയാളം", bcp47: "ml-IN" },
  { code: "mr", display_name: "Marathi", native_name: "मराठी", bcp47: "mr-IN" },
  { code: "bn", display_name: "Bengali", native_name: "বাংলা", bcp47: "bn-IN" },
  { code: "gu", display_name: "Gujarati", native_name: "ગુજરાતી", bcp47: "gu-IN" },
  { code: "pa", display_name: "Punjabi", native_name: "ਪੰਜਾਬੀ", bcp47: "pa-IN" },
];
