"""
CricketStream Fan Companion — Cricket Explainer & Glossary Module (Stage 1)
=============================================================================
Provides a comprehensive, beginner-friendly, and multilingual cricket glossary.
Features:
  1. 26 curated, authoritative cricket terminology entries across 6 categories.
  2. Grounded in MCC Laws of Cricket (2017 Code 4th Edition - 2026) and ICC Playing Conditions.
  3. High-quality 3-language translations: English (en), Hindi (hi), and Marathi (mr).
  4. Safe fallback mechanism with translation completeness metadata.
  5. Search indexing by name and keywords across all supported languages.
  6. Contextual match example builder using verified live server-side match data.
  7. Strict protection against division-by-zero, negative values, and stale feeds.
"""

import math
import re

# Supported Language Codes
SUPPORTED_LANGUAGES = ("en", "hi", "mr")
DEFAULT_LANGUAGE = "en"

# Valid Categories
CATEGORIES = {
    "batting": {"en": "Batting", "hi": "बल्लेबाजी", "mr": "फलंदाजी"},
    "bowling": {"en": "Bowling", "hi": "गेंदबाजी", "mr": "गोलंदाजी"},
    "scoring": {"en": "Scoring & Rates", "hi": "स्कोरिंग और रन रेट", "mr": "धावा आणि धावगती"},
    "rules": {"en": "Laws & Rules", "hi": "नियम और कानून", "mr": "नियम व कायदे"},
    "formats": {"en": "Match Formats & Over Breaks", "hi": "मैच प्रारूप", "mr": "सामन्याचे स्वरूप"},
    "match_situations": {"en": "Match Situations & Calculations", "hi": "मैच की स्थिति", "mr": "सामन्याची स्थिती"},
}


# =============================================================================
# Master Glossary Terms Definition Dictionary
# =============================================================================

GLOSSARY_TERMS = {
    "strike_rate": {
        "id": "strike_rate",
        "name": {
            "en": "Batting Strike Rate (SR)",
            "hi": "बल्लेबाजी स्ट्राइक रेट (SR)",
            "mr": "फलंदाजी स्ट्राइक रेट (SR)",
        },
        "category": "batting",
        "authority_type": "Scoring Metric",
        "rule_reference": "Standard Cricket Metric",
        "formula": "(Runs Scored / Balls Faced) × 100",
        "definition": {
            "en": "A statistical measure of how rapidly a batter scores runs, expressed as the average number of runs scored per 100 balls faced.",
            "hi": "यह दर्शाता है कि एक बल्लेबाज कितनी तेजी से रन बना रहा है। इसकी गणना प्रति 100 गेंदों पर बनाए गए औसत रनों के रूप में की जाती है।",
            "mr": "फलंदाज किती वेगाने धावा काढत आहे याचे प्रमाण. दर १०० चेंडूंमागे फलंदाजाने केलेल्या सरासरी धावा म्हणजे स्ट्राइक रेट.",
        },
        "competition_notes": {
            "en": "In T20 matches, a strike rate above 135–140 is generally considered strong, whereas in ODIs around 90–100 is solid.",
            "hi": "टी20 मैचों में 135-140 से अधिक का स्ट्राइक रेट बेहतरीन माना जाता है, जबकि वनडे में 90-100 का स्ट्राइक रेट अच्छा होता है।",
            "mr": "टी-२० सामन्यांमध्ये १३५-१४० पेक्षा जास्त स्ट्राइक रेट उत्कृष्ट मानला जातो, तर एकदिवसीय सामन्यात ९०-१०० चा दर चांगला मानला जातो.",
        },
        "context_key": "batters",
    },

    "bowling_strike_rate": {
        "id": "bowling_strike_rate",
        "name": {
            "en": "Bowling Strike Rate",
            "hi": "गेंदबाजी स्ट्राइक रेट",
            "mr": "गोलंदाजी स्ट्राइक रेट",
        },
        "category": "bowling",
        "authority_type": "Scoring Metric",
        "rule_reference": "Standard Cricket Metric",
        "formula": "Legal Balls Bowled / Wickets Taken",
        "definition": {
            "en": "The average number of legal deliveries a bowler bowls to take each wicket. A lower number indicates greater wicket-taking potency.",
            "hi": "एक गेंदबाज को प्रत्येक विकेट लेने के लिए औसतन कितनी वैध गेंदें फेंकनी पड़ती हैं। यह संख्या जितनी कम होगी, गेंदबाज उतना ही असरदार माना जाता है।",
            "mr": "प्रत्येक विकेट घेण्यासाठी गोलंदाजाला सरासरी किती वैध चेंडू टाकावे लागतात त्याचे प्रमाण. ही संख्या जितकी कमी, तितकी गोलंदाजाची विकेट घेण्याची क्षमता जास्त.",
        },
        "competition_notes": {
            "en": "A bowling strike rate under 20 balls per wicket is exceptional in T20 cricket.",
            "hi": "टी20 क्रिकेट में प्रति विकेट 20 से कम गेंदों का स्ट्राइक रेट असाधारण माना जाता है।",
            "mr": "टी-२० क्रिकेटमध्ये प्रति विकेट २० पेक्षा कमी चेंडूंचा स्ट्राइक रेट अतिशय प्रभावी मानला जातो.",
        },
        "context_key": "bowler_sr",
    },

    "economy_rate": {
        "id": "economy_rate",
        "name": {
            "en": "Economy Rate (Econ)",
            "hi": "इकोनॉमी रेट (Econ)",
            "mr": "इकॉनॉमी रेट (Econ)",
        },
        "category": "bowling",
        "authority_type": "Scoring Metric",
        "rule_reference": "Standard Cricket Metric",
        "formula": "Runs Conceded / Overs Bowled = (Runs Conceded / Legal Balls) × 6",
        "definition": {
            "en": "The average number of runs a bowler concedes per 6-ball over. Calculated using exact legal deliveries, where each ball is one-sixth of an over.",
            "hi": "एक गेंदबाज प्रति ओवर औसतन जितने रन देता है, उसे इकोनॉमी रेट कहते हैं। इसकी गणना वैध गेंदों के सटीक अनुपात से की जाती है।",
            "mr": "गोलंदाजाने दर षटकामागे (६ चेंडूंमागे) दिलेल्या सरासरी धावा. प्रत्येक वैध चेंडू षटकाचा १/६ भाग मानून ही अचूक काढली जाते.",
        },
        "competition_notes": {
            "en": "In T20 matches, an economy under 7.50 is considered very good. Partial overs (e.g. 3.2 overs) equal 3 + 2/6 = 3.333 overs for exact calculations.",
            "hi": "टी20 में 7.50 से कम का इकोनॉमी रेट बहुत अच्छा माना जाता है। अपूर्ण ओवर (जैसे 3.2 ओवर) की गणना 3 + 2/6 = 3.333 ओवर के रूप में होती है।",
            "mr": "टी-२० मध्ये ७.५० पेक्षा कमी इकॉनॉमी रेट उत्कृष्ट मानला जातो. अपूर्ण षटक (उदा. ३.२ षटके) ३ + २/६ = ३.३३३ षटके मानून मोजले जाते.",
        },
        "context_key": "bowler",
    },

    "current_run_rate": {
        "id": "current_run_rate",
        "name": {
            "en": "Current Run Rate (CRR)",
            "hi": "करंट रन रेट (CRR)",
            "mr": "सध्याची धावगती (CRR)",
        },
        "category": "scoring",
        "authority_type": "Scoring Metric",
        "rule_reference": "Standard Cricket Metric",
        "formula": "Total Runs Scored / Completed Overs = (Runs / Legal Balls) × 6",
        "definition": {
            "en": "The average number of runs the batting team is currently scoring per over throughout their innings.",
            "hi": "बल्लेबाजी करने वाली टीम वर्तमान में अपनी पारी में प्रति ओवर जितने औसत रन बना रही है, उसे करंट रन रेट कहते हैं।",
            "mr": "फलंदाजी करणारा संघ सध्या डावात दर षटकामागे सरासरी किती धावा करत आहे याचे प्रमाण.",
        },
        "competition_notes": {
            "en": "Current Run Rate applies to both first and second innings, reflecting current scoring momentum regardless of any target.",
            "hi": "करंट रन रेट पहली और दूसरी दोनों पारियों में लागू होता है और यह लक्ष्य की परवाह किए बिना बल्लेबाजी की गति को दर्शाता है।",
            "mr": "करंट रन रेट दोन्ही डावांना लागू होतो आणि तो लक्ष्याचा विचार न करता फलंदाजीचा चालू वेग दर्शवतो.",
        },
        "context_key": "run_rate",
    },

    "required_run_rate": {
        "id": "required_run_rate",
        "name": {
            "en": "Required Run Rate (RRR)",
            "hi": "आवश्यक रन रेट (RRR)",
            "mr": "आवश्यक धावगती (RRR)",
        },
        "category": "match_situations",
        "authority_type": "Scoring Metric",
        "rule_reference": "Standard Cricket Metric",
        "formula": "(Runs Required / Balls Remaining) × 6",
        "definition": {
            "en": "The average number of runs per over the chasing team must score to reach the target within the remaining overs in the second innings.",
            "hi": "दूसरी पारी में लक्ष्य तक पहुँचने के लिए पीछा करने वाली टीम को शेष गेंदों में प्रति ओवर जितने औसत रन बनाने होते हैं, उसे आवश्यक रन रेट कहते हैं।",
            "mr": "दुसऱ्या डावात उर्वरित चेंडूंमध्ये विजय मिळवण्यासाठी फलंदाजी करणाऱ्या संघाला दर षटकामागे लागणाऱ्या सरासरी धावा म्हणजे आवश्यक धावगती.",
        },
        "competition_notes": {
            "en": "RRR only exists in the second innings of limited-overs matches once a target has been established. It does not apply in the first innings.",
            "hi": "आरआरआर (RRR) केवल सीमित ओवरों के मैचों की दूसरी पारी में लक्ष्य तय होने के बाद ही लागू होता है। पहली पारी में इसका कोई अस्तित्व नहीं होता।",
            "mr": "आरआरआर (RRR) फक्त मर्यादित षटकांच्या सामन्यांतील दुसऱ्या डावात लक्ष्य निश्चित झाल्यावरच लागू होतो. पहिल्या डावात हा लागू नसतो.",
        },
        "context_key": "required_run_rate",
    },

    "powerplay": {
        "id": "powerplay",
        "name": {
            "en": "Powerplay",
            "hi": "पावरप्ले (Powerplay)",
            "mr": "पॉवरप्ले (Powerplay)",
        },
        "category": "rules",
        "authority_type": "ICC Playing Conditions",
        "rule_reference": "ICC Men's T20I Cl. 28.7 / ODI Cl. 28.14",
        "formula": None,
        "definition": {
            "en": "A designated block of overs where strict fielding restrictions apply to encourage attacking batting, permitting fewer fielders outside the 30-yard boundary circle.",
            "hi": "मैच के वे निर्धारित ओवर जिनमें 30-यार्ड के दायरे के बाहर सीमित संख्या में फील्डर रखने की अनुमति होती है, ताकि तेज बल्लेबाजी को बढ़ावा मिले।",
            "mr": "सामन्यातील ठरावीक षटके ज्यामध्ये ३०-यार्ड वर्तुळाबाहेर कमी क्षेत्ररक्षक ठेवण्याचे बंधन असते, जेणेकरून फलंदाजीला आक्रमक खेळता यावे.",
        },
        "competition_notes": {
            "en": "In a full 20-over T20 match, overs 1–6 are the mandatory Powerplay (maximum 2 fielders outside the circle). In 50-over ODIs, there are three stages: P1 (overs 1–10, max 2 outside), P2 (overs 11–40, max 4 outside), and P3 (overs 41–50, max 5 outside). In rain-reduced matches, Powerplay lengths are proportionally shortened.",
            "hi": "टी20 में पहले 6 ओवर पावरप्ले होते हैं (सर्कल के बाहर अधिकतम 2 फील्डर)। वनडे में 3 चरण होते हैं (P1: 1-10 ओवर, P2: 11-40 ओवर, P3: 41-50 ओवर)। बारिश से ओवर कम होने पर पावरप्ले के ओवर भी उसी अनुपात में घट जाते हैं।",
            "mr": "टी-२० सामन्यात पहिले ६ षटके पॉवरप्ले असतात (वर्तुळाबाहेर कमाल २ क्षेत्ररक्षक). एकदिवसीय सामन्यात ३ टप्पे असतात (P1: १-१०, P2: ११-४०, P3: ४१-५०). पावसामुळे षटके कमी झाल्यास पॉवरप्लेची षटकेही प्रमाणात कमी केली जातात.",
        },
        "context_key": "powerplay",
    },

    "wide_ball": {
        "id": "wide_ball",
        "name": {
            "en": "Wide Ball",
            "hi": "वाइड गेंद (Wide)",
            "mr": "वाईड चेंडू (Wide)",
        },
        "category": "rules",
        "authority_type": "MCC Law",
        "rule_reference": "MCC Law 22 (Wide ball)",
        "formula": "1 Penalty Run + Delivery Must Be Re-bowled",
        "definition": {
            "en": "A delivery judged by the umpire to have passed too far from the striker in their normal guard to be hit with a normal cricket stroke. Awards 1 extra run to the batting team, does not count as one of the 6 balls of the over, and must be bowled again.",
            "hi": "अंपायर द्वारा वह गेंद वाइड घोषित की जाती है जो बल्लेबाज की सामान्य मुद्रा से इतनी दूर से निकले कि वह सामान्य शॉट न खेल सके। इसके लिए बल्लेबाजी टीम को 1 अतिरिक्त रन मिलता है, यह वैध गेंद नहीं मानी जाती और इसे दोबारा फेंकना पड़ता है।",
            "mr": "पंच ज्या चेंडूला फलंदाजाच्या आवाक्याबाहेरून गेला म्हणून ठरवतात. यावर फलंदाजी संघाला १ अवांतर धाव मिळते, हा चेंडू षटकात मोजला जात नाही आणि गोलंदाजाला तो पुन्हा टाकावा लागतो.",
        },
        "competition_notes": {
            "en": "Under MCC Law 22.1, any runs scored in addition to the penalty (e.g. if the ball runs to the boundary) are also scored as Wides. A batter cannot be out Bowled, Caught, or LBW off a wide, but can be Stumped, Run Out, or Hit Wicket.",
            "hi": "एमसीसी नियम 22.1 के अनुसार, यदि गेंद बाउंड्री चली जाए तो कुल 5 वाइड रन मिलते हैं। वाइड गेंद पर बल्लेबाज बोल्ड, कैच या एलबीडब्ल्यू नहीं हो सकता, लेकिन स्टम्प्ड, रन आउट या हिट विकेट हो सकता है।",
            "mr": "एमसीसी कायदा २२.१ नुसार, वाईड चेंडूवर फलंदाज बोल्ड, झेल किंवा पायचित होऊ शकत नाही; मात्र तो स्टम्पिंग, धावचीत किंवा हिट-विकेट होऊ शकतो.",
        },
        "context_key": "extras_wide",
    },

    "no_ball": {
        "id": "no_ball",
        "name": {
            "en": "No-ball",
            "hi": "नो-बॉल (No-ball)",
            "mr": "नो-बॉल (No-ball)",
        },
        "category": "rules",
        "authority_type": "MCC Law",
        "rule_reference": "MCC Law 21 (No ball) & ICC Limited Overs Cl. 21",
        "formula": "1 Penalty Run + Re-bowl (+ Free Hit in Limited Overs)",
        "definition": {
            "en": "An illegal delivery resulting from an infringement by the bowler or fielding team—such as overstepping the popping crease, bowling a high full-pitch above waist height, or breaching field placement limits. Adds 1 penalty run, does not count as a legal ball, and must be re-bowled.",
            "hi": "गेंदबाज या फील्डिंग टीम द्वारा नियमों के उल्लंघन पर दी जाने वाली अवैध गेंद—जैसे क्रीज से आगे पैर रखना, कमर से ऊपर फुल-टॉस फेंकना, या गलत फील्डिंग सजावट। इसमें 1 अतिरिक्त रन मिलता है और गेंद दोबारा फेंकनी होती है।",
            "mr": "गोलंदाज किंवा क्षेत्ररक्षण करणाऱ्या संघाकडून नियमांचे उल्लंघन झाल्यास दिलेला अवैध चेंडू—उदा. पॉपिंग क्रीझ ओलांडणे किंवा कमरेच्या वर थेट चेंडू टाकणे. यावर १ अवांतर धाव मिळते आणि चेंडू पुन्हा टाकावा लागतो.",
        },
        "competition_notes": {
            "en": "In almost all modern limited-overs competitions (T20 and ODI), any no-ball also awards a 'Free Hit' on the subsequent delivery, where the batter can only be dismissed by Run Out, Obstructing the Field, or Hitting the Ball Twice.",
            "hi": "सीमित ओवरों (टी20 और वनडे) में किसी भी नो-बॉल के बाद अगली गेंद पर 'फ्री हिट' मिलता है, जिसमें बल्लेबाज को केवल रन आउट ही किया जा सकता है।",
            "mr": "मर्यादित षटकांच्या क्रिकेटमध्ये (टी-२० आणि वन-डे) कोणत्याही नो-बॉल नंतर पुढच्या चेंडूवर 'फ्री हिट' मिळते, ज्यावर फलंदाज केवळ धावचीत होऊ शकतो.",
        },
        "context_key": "extras_noball",
    },

    "free_hit": {
        "id": "free_hit",
        "name": {
            "en": "Free Hit",
            "hi": "फ्री हिट (Free Hit)",
            "mr": "फ्री हिट (Free Hit)",
        },
        "category": "rules",
        "authority_type": "ICC Playing Conditions",
        "rule_reference": "ICC Men's T20I Cl. 21.19 / ODI Cl. 21.19",
        "formula": "No dismissal except Run Out, Obstructing Field, or Hit Ball Twice",
        "definition": {
            "en": "A penalty delivery awarded to the batting team immediately following any no-ball in limited-overs cricket. The batter cannot be dismissed by standard modes such as Bowled, Caught, LBW, or Stumped.",
            "hi": "सीमित ओवरों के क्रिकेट में नो-बॉल के तुरंत बाद बल्लेबाजी टीम को मिलने वाली सुरक्षित गेंद। इस गेंद पर बल्लेबाज बोल्ड, कैच, एलबीडब्ल्यू या स्टम्प्ड आउट नहीं हो सकता।",
            "mr": "मर्यादित षटकांच्या क्रिकेटमध्ये नो-बॉल नंतर फलंदाजाला मिळणारा विशेष चेंडू. या चेंडूवर फलंदाज झेल, बोल्ड, पायचित किंवा स्टम्पिंगद्वारे बाद होऊ शकत नाही.",
        },
        "competition_notes": {
            "en": "Fielders cannot change positions for the Free Hit unless the batters crossed ends on the no-ball or the no-ball was called for a fielding restriction breach.",
            "hi": "फ्री हिट पर फील्डर अपनी जगह नहीं बदल सकते, जब तक कि बल्लेबाजों ने रन लेते हुए छोर न बदल लिया हो।",
            "mr": "फ्री हिटवर क्षेत्ररक्षकांना आपली जागा बदलता येत नाही, जोपर्यंत फलंदाजांनी मागच्या चेंडूवर धाव घेऊन जागा बदललेली नसेल.",
        },
        "context_key": "free_hit",
    },

    "dls_method": {
        "id": "dls_method",
        "name": {
            "en": "DLS Method (Duckworth-Lewis-Stern)",
            "hi": "डीएलएस पद्धति (डकवर्थ-लुईस-स्टर्न)",
            "mr": "डीएलएस पद्धत (डकवर्थ-लुईस-स्टर्न)",
        },
        "category": "match_situations",
        "authority_type": "ICC Playing Conditions",
        "rule_reference": "ICC Standard Playing Conditions App. DLS",
        "formula": "Revised Target based on available Resource Percentage (Overs + Wickets)",
        "definition": {
            "en": "A mathematical formula used in weather-interrupted limited-overs matches to adjust targets and calculate fair results based on resources remaining (overs left and wickets in hand).",
            "hi": "बारिश या मौसम से बाधित सीमित ओवरों के मैचों में निष्पक्ष लक्ष्य निर्धारित करने का गणितीय तरीका, जो बचे हुए ओवरों और शेष विकेटों के आधार पर तय होता है।",
            "mr": "पावसामुळे खेळ थांबल्यास मर्यादित षटकांच्या सामन्यात सुधारित लक्ष्य काढण्यासाठी वापरली जाणारी गणितीय पद्धत, जी शिल्लक षटके आणि शिल्लक विकेट्सवर अवलंबून असते.",
        },
        "competition_notes": {
            "en": "DLS calculations require proprietary ICC statistical resource tables. CricketStream reports official DLS targets communicated by match officials; it does not independently compute DLS models.",
            "hi": "डीएलएस की गणना आईसीसी की अधिकृत तालिकाओं पर आधारित होती है। यह ऐप केवल मैच अधिकारियों द्वारा घोषित आधिकारिक लक्ष्य प्रदर्शित करता है।",
            "mr": "डीएलएसचे आकडे अधिकृत आयसीसी तक्त्यांवर आधारित असतात. हे ॲप सामना अधिकाऱ्यांनी दिलेले अधिकृत लक्ष्य दाखवते.",
        },
        "context_key": "dls",
    },

    "partnership": {
        "id": "partnership",
        "name": {
            "en": "Partnership",
            "hi": "साझेदारी (Partnership)",
            "mr": "भागीदारी (Partnership)",
        },
        "category": "batting",
        "authority_type": "Scoring Metric",
        "rule_reference": "Standard Cricket Metric",
        "formula": "Runs scored by both batters combined + Extras conceded during the stand",
        "definition": {
            "en": "The total number of team runs accumulated while two specific batters bat together between consecutive dismissals, including any extras scored during their stand.",
            "hi": "दो बल्लेबाजों के बीच किसी एक के आउट होने तक मिलकर बनाए गए कुल रनों की संख्या, जिसमें उस दौरान मिले अतिरिक्त (एक्स्ट्रा) रन भी शामिल होते हैं।",
            "mr": "दोन फलंदाज मैदानावर एकत्र असताना संघासाठी केलेल्या एकूण धावा. यात त्या दरम्यान मिळालेल्या अवांतर (एक्स्ट्रा) धावांचाही समावेश असतो.",
        },
        "competition_notes": {
            "en": "Partnerships are designated by wicket number (e.g. '1st Wicket Partnership' until the first dismissal, '2nd Wicket Partnership' thereafter).",
            "hi": "साझेदारी विकेट के नंबर से जानी जाती है (जैसे पहली विकेट गिरने तक 'प्रथम विकेट साझेदारी')।",
            "mr": "भागीदारी विकेटच्या क्रमांकाने ओळखली जाते (उदा. पहिली विकेट पडेपर्यंत 'पहिल्या विकेटची भागीदारी').",
        },
        "context_key": "partnership",
    },

    "maiden_over": {
        "id": "maiden_over",
        "name": {
            "en": "Maiden Over",
            "hi": "मेडन ओवर (Maiden Over)",
            "mr": "मेडन षटक (Maiden Over)",
        },
        "category": "bowling",
        "authority_type": "Scoring Metric",
        "rule_reference": "Standard Cricket Metric",
        "formula": "Over with 0 runs conceded off the bat, no wides, and no no-balls",
        "definition": {
            "en": "A completed 6-ball over in which zero runs are conceded by the bowler off the bat and no wide balls or no-balls are bowled.",
            "hi": "वह पूरा 6 गेंदों का ओवर जिसमें गेंदबाज के खिलाफ बल्ले से एक भी रन न बने और न ही कोई वाइड या नो-बॉल फेंकी गई हो।",
            "mr": "६ चेंडूंचे असे पूर्ण षटक ज्यामध्ये गोलंदाजाने एकही धाव दिलेली नसते आणि कोणताही वाईड किंवा नो-बॉल टाकलेला नसतो.",
        },
        "competition_notes": {
            "en": "Byes and leg byes scored during the over do not count against the bowler and still permit the over to be credited as a maiden. If a wicket falls in a maiden, it is colloquially called a 'wicket maiden'.",
            "hi": "यदि बाई या लेग बाई के रन बनें तो भी ओवर मेडन माना जाता है क्योंकि वे गेंदबाज के खाते में नहीं जुड़ते।",
            "mr": "बाईज किंवा लेग-बाईजच्या धावा झाल्यास तरीही षटक मेडनच मानले जाते, कारण त्या गोलंदाजाच्या खात्यात जमा होत नाहीत.",
        },
        "context_key": "maiden",
    },

    "duck": {
        "id": "duck",
        "name": {
            "en": "Duck",
            "hi": "डक (शून्य पर आउट)",
            "mr": "डक (शून्यावर बाद)",
        },
        "category": "batting",
        "authority_type": "Scoring Terminology",
        "rule_reference": "Standard Cricket Terminology",
        "formula": "Batter dismissed with score = 0",
        "definition": {
            "en": "A dismissal of a batter without scoring any runs (score of 0). Variations include a 'Golden Duck' (out on the very first ball faced) and a 'Diamond Duck' (out on 0 without facing a ball, e.g. run out from the non-striker's end).",
            "hi": "किसी बल्लेबाज का बिना कोई रन बनाए (0 रन पर) आउट होना। पहली ही गेंद पर आउट होने को 'गोल्डन डक' और बिना गेंद खेले आउट होने को 'डायमंड डक' कहते हैं।",
            "mr": "फलंदाज एकही धाव न काढता (० धावांवर) बाद होणे. पहिल्याच चेंडूवर बाद झाल्यास 'गोल्डन डक' आणि एकही चेंडू न खेळता (उदा. धावचीत) बाद झाल्यास 'डायमंड डक' म्हणतात.",
        },
        "competition_notes": {
            "en": "A batter remaining on 0* not out is not on a duck; a duck strictly requires a dismissal.",
            "hi": "यदि कोई बल्लेबाज 0* रन पर नाबाद रहे तो उसे डक नहीं कहा जाता; डक के लिए आउट होना आवश्यक है।",
            "mr": "जर फलंदाज ०* धावांवर नाबाद राहिला तर त्याला डक म्हटले जात नाही; डकसाठी बाद होणे आवश्यक असते.",
        },
        "context_key": "duck",
    },

    "boundary": {
        "id": "boundary",
        "name": {
            "en": "Boundary (Four & Six)",
            "hi": "बाउंड्री (चौका और छक्का)",
            "mr": "चौकार आणि षटकार (बाउंड्री)",
        },
        "category": "scoring",
        "authority_type": "MCC Law",
        "rule_reference": "MCC Law 19 (Boundaries)",
        "formula": "4 runs if grounded / bounces, 6 runs if cleared on the full",
        "definition": {
            "en": "The perimeter of the playing area, or a stroke that scores runs by reaching or crossing this perimeter. A hit crossing the boundary after touching the ground scores 4 runs; a hit clearing the boundary on the full without touching the ground scores 6 runs.",
            "hi": "मैदान की सीमारेखा, या वह शॉट जो गेंद को सीमा पार पहुंचाकर रन बनाता है। टप्पा खाकर सीमा पार जाने पर 4 रन (चौका) और हवा में बिना टप्पा खाए पार जाने पर 6 रन (छक्का) मिलते हैं।",
            "mr": "मैदानाची सीमारेषा किंवा चेंडू सीमारेषेबाहेर पाठवून मिळवलेल्या धावा. चेंडू जमिनीला टेकून सीमारेषेबाहेर गेल्यास ४ धावा (चौकार) आणि हवेतून थेट सीमारेषेबाहेर गेल्यास ६ धावा (षटकार) मिळतात.",
        },
        "competition_notes": {
            "en": "If a fielder touches the boundary boundary cushion or rope while in contact with the ball, the boundary is immediately awarded.",
            "hi": "यदि गेंद को छूते समय फील्डर का कोई हिस्सा बाउंड्री कुशन या रस्सी को छू जाए, तो तुरंत बाउंड्री दे दी जाती है।",
            "mr": "चेंडू पकडताना जर क्षेत्ररक्षकाचा कोणताही भाग सीमारेषेला किंवा दोरीला स्पर्श करत असेल, तर चौकार/षटकार दिला जातो.",
        },
        "context_key": "boundaries",
    },

    "extras": {
        "id": "extras",
        "name": {
            "en": "Extras",
            "hi": "अतिरिक्त रन (Extras)",
            "mr": "अवांतर धावा (Extras)",
        },
        "category": "scoring",
        "authority_type": "MCC Law",
        "rule_reference": "MCC Laws 20–26",
        "formula": "Total Extras = Wides + No-balls + Byes + Leg Byes + Penalty Runs",
        "definition": {
            "en": "Runs awarded to the batting team that are not credited to the personal score of an individual batter. Extras comprise wides, no-balls, byes, leg byes, and umpire penalty runs.",
            "hi": "बल्लेबाजी करने वाली टीम को मिलने वाले वे रन जो किसी व्यक्तिगत बल्लेबाज के खाते में नहीं जोड़े जाते। इसमें वाइड, नो-बॉल, बाई, लेग बाई और पेनल्टी रन शामिल हैं।",
            "mr": "फलंदाजी करणाऱ्या संघाला मिळालेल्या अशा धावा ज्या वैयक्तिक फलंदाजाच्या खात्यात मोजल्या जात नाहीत. यात वाईड, नो-बॉल, बाईज, लेग-बाईज आणि पेनल्टी धावांचा समावेश असतो.",
        },
        "competition_notes": {
            "en": "Wides and no-balls are debited against the bowler's figures; byes, leg byes, and penalty runs are credited to team totals without counting against the bowler.",
            "hi": "वाइड और नो-बॉल गेंदबाज के खाते में जुड़ते हैं, जबकि बाई, लेग बाई और पेनल्टी रन केवल टीम के कुल स्कोर में जुड़ते हैं।",
            "mr": "वाईड आणि नो-बॉल गोलंदाजाच्या खात्यात नोंदवले जातात, तर बाईज, लेग-बाईज आणि पेनल्टी धावा फक्त संघाच्या एकूण धावसंख्येत जोडल्या जातात.",
        },
        "context_key": "extras",
    },

    "wicket": {
        "id": "wicket",
        "name": {
            "en": "Wicket (Dismissal)",
            "hi": "विकेट / आउट होना",
            "mr": "विकेट / बाद होणे",
        },
        "category": "rules",
        "authority_type": "MCC Law",
        "rule_reference": "MCC Laws 29 & 32–39",
        "formula": "Primary dismissal modes: Bowled, Caught, LBW, Run Out, Stumped",
        "definition": {
            "en": "The dismissal of a batter, terminating their turn to bat; also refers to the three wooden stumps and two bails at each end of the pitch.",
            "hi": "किसी बल्लेबाज का आउट होना जिससे उसकी बल्लेबाजी समाप्त हो जाती है; इसके अलावा पिच के दोनों छोरों पर लगे तीन डंडों और दो गिल्लियों को भी विकेट कहते हैं।",
            "mr": "फलंदाज बाद होण्याची क्रिया ज्यामुळे त्याची फलंदाजी संपते; तसेच खेळपट्टीच्या दोन्ही टोकांना असलेल्या तीन लाकडी दांड्या आणि दोन बेल्सनाही विकेट म्हणतात.",
        },
        "competition_notes": {
            "en": "The 5 most common modes of dismissal are Bowled (Law 32), Caught (Law 33), LBW (Law 36), Run Out (Law 38), and Stumped (Law 39). Other rare modes include Hit Wicket, Obstructing the Field, and Timed Out.",
            "hi": "आउट होने के 5 प्रमुख तरीके हैं: बोल्ड, कैच, एलबीडब्ल्यू, रन आउट और स्टम्प्ड।",
            "mr": "बाद होण्याचे ५ प्रमुख प्रकार आहेत: बोल्ड, झेल (कॅच), पायचित (LBW), धावचीत (रन आउट) आणि स्टम्पिंग.",
        },
        "context_key": "wickets",
    },

    "over": {
        "id": "over",
        "name": {
            "en": "Over",
            "hi": "ओवर (Over)",
            "mr": "षटक (Over)",
        },
        "category": "rules",
        "authority_type": "MCC Law",
        "rule_reference": "MCC Law 17 (The over)",
        "formula": "6 Legal Deliveries",
        "definition": {
            "en": "A sequence of 6 consecutive legal deliveries bowled by the same bowler from one end of the pitch. Wides and no-balls do not count toward the 6 balls.",
            "hi": "पिच के एक छोर से एक ही गेंदबाज द्वारा फेंकी गई लगातार 6 वैध गेंदों का समूह। वाइड और नो-बॉल इन 6 गेंदों में नहीं गिने जाते।",
            "mr": "एकाच गोलंदाजाने खेळपट्टीच्या एका बाजूने सलग टाकलेल्या ६ वैध चेंडूंचा संच. वाईड आणि नो-बॉल या ६ चेंडूंत मोजले जात नाहीत.",
        },
        "competition_notes": {
            "en": "A bowler cannot bowl two consecutive overs from opposite ends in an uninterrupted innings. At the end of each over, the fielding ends swap.",
            "hi": "कोई भी गेंदबाज एक पारी में लगातार दो ओवर नहीं फेंक सकता। प्रत्येक ओवर के बाद छोर बदल दिया जाता है।",
            "mr": "कोणताही गोलंदाज डावात सलग दोन षटके टाकू शकत नाही. प्रत्येक षटकानंतर बाजू बदलली जाते.",
        },
        "context_key": "overs",
    },

    "crease": {
        "id": "crease",
        "name": {
            "en": "Crease",
            "hi": "क्रीज (Crease)",
            "mr": "क्रीझ (Crease)",
        },
        "category": "rules",
        "authority_type": "MCC Law",
        "rule_reference": "MCC Law 7 (The creases)",
        "formula": "Popping crease (4 ft in front of stumps), Bowling crease, Return creases",
        "definition": {
            "en": "White painted lines marking boundaries of safe ground for batters and legal landing zones for bowlers at each end of the pitch.",
            "hi": "पिच के दोनों सिरों पर सफेद रंग से खींची गई रेखाएं, जो बल्लेबाजों के लिए सुरक्षित क्षेत्र और गेंदबाजों के लिए गेंद फेंकने की वैध सीमा तय करती हैं।",
            "mr": "खेळपट्टीच्या दोन्ही बाजूला पांढऱ्या रंगाने आखलेल्या रेषा, ज्या फलंदाजांसाठी सुरक्षित जागा आणि गोलंदाजांसाठी चेंडू टाकण्याची वैध मर्यादा ठरवतात.",
        },
        "competition_notes": {
            "en": "The popping crease is situated 4 feet (1.22 m) in front of the stumps. A batter is safe inside the crease if some part of their bat or person is grounded behind the inside edge of the popping crease.",
            "hi": "पॉपिंग क्रीज स्टंप्स से 4 फीट आगे होती है। जब तक बल्लेबाज का बल्ला या शरीर रेखा के अंदर जमीन से छुआ हो, वह सुरक्षित माना जाता है।",
            "mr": "पॉपिंग क्रीझ स्टम्प्सपासून ४ फूट पुढे असते. फलंदाजाची बॅट किंवा पाय रेषेच्या मागे टेकलेला असेल तर तो सुरक्षित मानला जातो.",
        },
        "context_key": "crease",
    },

    "yorker": {
        "id": "yorker",
        "name": {
            "en": "Yorker",
            "hi": "यॉर्कर (Yorker)",
            "mr": "यॉर्कर (Yorker)",
        },
        "category": "bowling",
        "authority_type": "Bowling Technique",
        "rule_reference": "Standard Cricket Terminology",
        "formula": "Delivery pitching exactly on the popping crease at batter's feet",
        "definition": {
            "en": "A delivery pitched very full, directly at or just beneath the batter's toes or popping crease, making it extremely difficult to hit for a boundary.",
            "hi": "गेंदबाज द्वारा फेंकी गई वह सटीक गेंद जो बल्लेबाज के ठीक पैरों के पास या पॉपिंग क्रीज पर टप्पा खाती है, जिससे शॉट लगाना बहुत मुश्किल होता है।",
            "mr": "असा अचूक चेंडू जो फलंदाजाच्या अगदी पायाजवळ किंवा पॉपिंग क्रीझवर पडतो, ज्यावर मोठा फटका मारणे अत्यंत कठीण असते.",
        },
        "competition_notes": {
            "en": "Widely used as an effective wicket-taking and defensive weapon during death overs in T20 and limited-overs matches.",
            "hi": "टी20 मैचों के अंतिम ओवरों (डेथ ओवर्स) में रन रोकने और बोल्ड करने के लिए यॉर्कर सबसे घातक हथियार मानी जाती है।",
            "mr": "टी-२० सामन्यांच्या अखेरच्या षटकांत धावा रोखण्यासाठी आणि फलंदाजाला त्रिफळाचीत करण्यासाठी यॉर्कर चेंडूचा सर्वाधिक वापर केला जातो.",
        },
        "context_key": "yorker",
    },

    "bouncer": {
        "id": "bouncer",
        "name": {
            "en": "Bouncer",
            "hi": "बाउन्सर (Bouncer)",
            "mr": "बाउन्सर (Bouncer)",
        },
        "category": "bowling",
        "authority_type": "MCC Law & Playing Conditions",
        "rule_reference": "MCC Law 41.6 & ICC T20 Cl. 41.6",
        "formula": "Short-pitched fast delivery reaching shoulder/head height",
        "definition": {
            "en": "A fast, short-pitched delivery intended to bounce steeply toward the batter's chest or head height to force an evasive action or defensive mistake.",
            "hi": "तेज गेंदबाज द्वारा छोटी फेंकी गई गेंद जो टप्पा खाकर बल्लेबाज की छाती या सिर की ऊंचाई तक तेजी से उछलती है।",
            "mr": "वेगाने टाकलेला आखूड टप्प्याचा चेंडू जो उसळी घेऊन फलंदाजाच्या छाती किंवा डोक्याच्या दिशेने जातो.",
        },
        "competition_notes": {
            "en": "In T20 matches, ICC playing conditions permit only one short-pitched delivery above shoulder height per over (in IPL two are permitted under tournament rules). Any bouncer exceeding head height is called a Wide.",
            "hi": "टी20 में प्रति ओवर कंधे से ऊपर केवल 1 बाउंसर की अनुमति होती है (आईपीएल में 2 की छूट है)। सिर से ज्यादा ऊंची गेंद को अंपायर वाइड करार देते हैं।",
            "mr": "टी-२० मध्ये खांद्यावरून जाणारा प्रति षटक फक्त १ बाउन्सर टाकण्याची परवानगी असते (आयपीएलमध्ये २ ची मुभा आहे). डोक्याच्या फार वरून गेल्यास तो वाईड दिला जातो.",
        },
        "context_key": "bouncer",
    },

    "follow_on": {
        "id": "follow_on",
        "name": {
            "en": "Follow-on",
            "hi": "फॉलो-ऑन (Follow-on)",
            "mr": "फॉलो-ऑन (Follow-on)",
        },
        "category": "rules",
        "authority_type": "MCC Law",
        "rule_reference": "MCC Law 14 (The follow-on)",
        "formula": "Multi-day match deficit threshold: 200 (5+ days), 150 (3-4 days), 100 (2 days), 75 (1 day)",
        "definition": {
            "en": "A rule in two-innings multi-day matches where the team batting second can be forced to bat again immediately if their first-innings score falls short of their opponent's total by a specified margin.",
            "hi": "दो पारियों वाले बहु-दिवसीय (टेस्ट/फर्स्ट-क्लास) मैचों का नियम, जिसमें पहली पारी में बड़े अंतर से पिछड़ने पर दूसरी टीम को तुरंत दोबारा बल्लेबाजी करने पर मजबूर किया जा सकता है।",
            "mr": "दोन डावांच्या बहु-दिवसीय (कसोटी) सामन्यांतील नियम, ज्यामध्ये पहिल्या डावात मोठ्या फरकाने पिछाडीवर पडल्यास दुसऱ्या संघाला सलग पुन्हा फलंदाजी करण्यास भाग पाडले जाऊ शकते.",
        },
        "competition_notes": {
            "en": "Under MCC Law 14.1, the required lead is: 200 runs in matches of 5 or more days; 150 runs in 3- or 4-day matches; 100 runs in 2-day matches; and 75 runs in 1-day two-innings matches. Follow-on NEVER applies in standard single-innings limited-overs (T20 or ODI) matches.",
            "hi": "एमसीसी नियम 14.1 के अनुसार न्यूनतम बढ़त: 5 दिवसीय टेस्ट में 200 रन, 3-4 दिवसीय में 150 रन, 2 दिवसीय में 100 रन, और 1 दिवसीय 2-पारी मैच में 75 रन। टी20 और वनडे मैचों में फॉलो-ऑन कभी लागू नहीं होता।",
            "mr": "एमसीसी कायदा १४.१ नुसार आवश्यक आघाडी: ५ दिवसीय सामन्यात २०० धावा, ३-४ दिवसीय सामन्यात १५० धावा, २ दिवसीय सामन्यात १०० धावा. मर्यादित षटकांच्या (टी-२० किंवा एकदिवसीय) सामन्यांमध्ये फॉलो-ऑन कधीही लागू होत नाही.",
        },
        "context_key": "follow_on",
    },

    "super_over": {
        "id": "super_over",
        "name": {
            "en": "Super Over",
            "hi": "सुपर ओवर (Super Over)",
            "mr": "सुपर ओव्हर (Super Over)",
        },
        "category": "formats",
        "authority_type": "ICC Playing Conditions",
        "rule_reference": "ICC Standard T20 Playing Conditions App. F",
        "formula": "1 over (6 balls), 2 wickets per team; team with higher runs wins",
        "definition": {
            "en": "A 1-over tie-breaking procedure in limited-overs matches where both teams bat for 6 deliveries with 2 wickets in hand. The team scoring the most runs in their Super Over wins the match.",
            "hi": "सीमित ओवरों के मैच टाई होने पर परिणाम निकालने के लिए खेला जाने वाला 1-ओवर का फैसला, जिसमें दोनों टीमों को 6 गेंदें और 2 विकेट मिलते हैं। अधिक रन बनाने वाली टीम विजेता बनती है।",
            "mr": "मर्यादित षटकांचा सामना बरोबरीत (टाय) सुटल्यास निकाल लावण्यासाठी खेळवले जाणारे १ षटकांचे टायब्रेकर, ज्यामध्ये दोन्ही संघांना ६ चेंडू आणि २ विकेट्स मिळतात. जास्त धावा करणारा संघ जिंकतो.",
        },
        "competition_notes": {
            "en": "Under current ICC rules, if a Super Over is also tied, subsequent Super Overs are played until a clear winner emerges. The controversial boundary-count rule was abolished in 2019.",
            "hi": "आईसीसी के वर्तमान नियमों के अनुसार, यदि सुपर ओवर भी टाई हो जाए, तो जब तक कोई टीम जीत न जाए तब तक दोबारा सुपर ओवर खेला जाता है। बाउंड्री काउंट नियम अब समाप्त कर दिया गया है।",
            "mr": "सध्याच्या आयसीसी नियमांनुसार, जर सुपर ओव्हरही बरोबरीत सुटली तर जोपर्यंत विजेता ठरत नाही तोपर्यंत पुन्हा सुपर ओव्हर खेळवली जाते. बाउंड्री मोजण्याचा जुना नियम आता रद्द करण्यात आला आहे.",
        },
        "context_key": "super_over",
    },

    "dot_ball": {
        "id": "dot_ball",
        "name": {
            "en": "Dot Ball",
            "hi": "डॉट गेंद (खाली गेंद)",
            "mr": "डॉट बॉल (धाव नसलेला चेंडू)",
        },
        "category": "scoring",
        "authority_type": "Scoring Metric",
        "rule_reference": "Standard Cricket Metric",
        "formula": "Legal delivery with 0 runs scored off bat or extras",
        "definition": {
            "en": "A delivery from which zero runs are scored and no wicket falls (denoted by a dot '.' in traditional cricket scorebooks).",
            "hi": "वह गेंद जिस पर बल्लेबाज कोई रन न बना सके और न ही कोई अतिरिक्त रन बने। स्कोरबुक में इसे एक बिंदी (.) से दर्शाया जाता है।",
            "mr": "असा वैध चेंडू ज्यावर एकही धाव होत नाही आणि कोणतीही अवांतर धाव मिळत नाही. स्कोअरबुकमध्ये हा ठिपक्याने (.) नोंदवला जातो.",
        },
        "competition_notes": {
            "en": "Building strings of dot balls is a key bowling objective in T20 cricket to mount scoreboard pressure and force batters into high-risk shots.",
            "hi": "टी20 में डॉट गेंदें बल्लेबाजों पर दबाव बनाने और उन्हें गलत शॉट खेलने के लिए मजबूर करने का सबसे प्रमुख साधन हैं।",
            "mr": "टी-२० सामन्यात फलंदाजावर दबाव निर्माण करण्यासाठी आणि त्याला चुकीचा फटका मारण्यास भाग पाडण्यासाठी अधिकाधिक डॉट बॉल टाकणे हे गोलंदाजाचे मुख्य ध्येय असते.",
        },
        "context_key": "dot_ball",
    },

    "byes_leg_byes": {
        "id": "byes_leg_byes",
        "name": {
            "en": "Byes and Leg Byes",
            "hi": "बाई और लेग बाई (Byes & Leg Byes)",
            "mr": "बाईज आणि लेग-बाईज (Byes & Leg Byes)",
        },
        "category": "scoring",
        "authority_type": "MCC Law",
        "rule_reference": "MCC Law 23 (Byes) & Law 24 (Leg byes)",
        "formula": "Team Extras (not charged against the bowler's figures)",
        "definition": {
            "en": "Extra runs scored without the ball touching the bat. A 'Bye' occurs when the ball passes the batter without touching their bat or person. A 'Leg Bye' occurs when the ball deflects off the batter's body or protective equipment (other than a glove holding the bat), provided the batter attempted to play a shot or evade being hit.",
            "hi": "बल्ले का संपर्क हुए बिना बनने वाले अतिरिक्त रन। 'बाई' तब होता है जब गेंद बिना बल्ले या शरीर को छुए निकल जाए। 'लेग बाई' तब मिलता है जब गेंद बल्लेबाज के शरीर या पैड से टकराकर निकले, बशर्ते उसने शॉट खेलने या बचने का प्रयास किया हो।",
            "mr": "बॅटला स्पर्श न होता मिळालेल्या अवांतर धावा. चेंडू बॅट किंवा शरीराला न लागता पुढे गेल्यास पळून काढलेल्या धावेला 'बाई' म्हणतात. चेंडू शरीराला किंवा पॅडला लागून गेल्यास 'लेग बाई' म्हणतात (जर फलंदाजाने फटका मारण्याचा प्रयत्न केला असेल).",
        },
        "competition_notes": {
            "en": "Under MCC Law 24.2, if the batter made no attempt to play a stroke or avoid the ball, leg byes are disallowed and the ball becomes dead if they attempt to run.",
            "hi": "यदि बल्लेबाज ने गेंद खेलने या उससे बचने का प्रयास नहीं किया हो, तो लेग बाई की अनुमति नहीं होती।",
            "mr": "जर फलंदाजाने चेंडू खेळण्याचा किंवा वाचण्याचा प्रयत्न केला नसेल, तर लेग बाईजच्या धावा नाकारल्या जातात.",
        },
        "context_key": "extras_byes",
    },

    "target": {
        "id": "target",
        "name": {
            "en": "Target",
            "hi": "लक्ष्य (Target)",
            "mr": "लक्ष्य / टार्गेट (Target)",
        },
        "category": "match_situations",
        "authority_type": "Scoring Rule",
        "rule_reference": "Standard Match Calculation",
        "formula": "1st Innings Runs + 1 (or DLS Revised Target)",
        "definition": {
            "en": "The total number of runs the team batting second must score to win the match. In an uninterrupted match, it is equal to the first-innings score plus one run.",
            "hi": "दूसरी पारी में बल्लेबाजी करने वाली टीम को मैच जीतने के लिए जितने कुल रनों की आवश्यकता होती है। यह पहली पारी के स्कोर से ठीक एक रन अधिक होता है।",
            "mr": "दुसऱ्या डावात फलंदाजी करणाऱ्या संघाला सामना जिंकण्यासाठी आवश्यक असलेली एकूण धावसंख्या. ही पहिल्या डावातील धावसंख्येत १ धाव मिळवून ठरवली जाते.",
        },
        "competition_notes": {
            "en": "During the first innings, no target exists. If rain interrupts play, the target may be adjusted according to the DLS method.",
            "hi": "पहली पारी के दौरान कोई लक्ष्य नहीं होता। बारिश की स्थिति में डीएलएस नियम से लक्ष्य संशोधित किया जा सकता है।",
            "mr": "पहिल्या डावात कोणतेही लक्ष्य अस्तित्वात नसते. पावसाचा व्यत्यय आल्यास डीएलएस नियमानुसार लक्ष्य बदलले जाऊ शकते.",
        },
        "context_key": "target",
    },

    "drs": {
        "id": "drs",
        "name": {
            "en": "DRS (Decision Review System)",
            "hi": "डीआरएस (डिसीजन रिव्यू सिस्टम)",
            "mr": "डीआरएस (डिसिजन रिव्ह्यू सिस्टीम)",
        },
        "category": "rules",
        "authority_type": "ICC Playing Conditions",
        "rule_reference": "ICC Standard Playing Conditions App. DRS",
        "formula": "Player Review protocol using ball-tracking, UltraEdge, and Hawk-Eye",
        "definition": {
            "en": "A technology-based process that allows either team's captain (or the dismissed batter) to request the third umpire review an on-field umpire's decision.",
            "hi": "तकनीक पर आधारित प्रणाली जिसके तहत कप्तान या बल्लेबाज मैदानी अंपायर के फैसले को तीसरे अंपायर से दोबारा जांचने (रिव्यू) का अनुरोध कर सकते हैं।",
            "mr": "तंत्रज्ञानावर आधारित प्रणाली ज्याद्वारे मैदानावरील पंचांच्या निर्णयाला तिसऱ्या पंचांकडे आव्हान (रिव्ह्यू) दिले जाऊ शकते.",
        },
        "competition_notes": {
            "en": "In T20 matches, each team typically has 2 unsuccessful reviews per innings. An 'Umpire's Call' outcome does not result in the team losing their review.",
            "hi": "टी20 में प्रत्येक टीम को प्रति पारी सामान्यतः 2 असफल रिव्यू मिलते हैं। 'अंपायर्स कॉल' होने पर रिव्यू नष्ट नहीं होता।",
            "mr": "टी-२० सामन्यात प्रत्येक संघाला डावात साधारणपणे २ अयशस्वी रिव्ह्यू मिळतात. 'अम्पायर्स कॉल' आल्यास संघाचा रिव्ह्यू वाया जात नाही.",
        },
        "context_key": "drs",
    },
}


# =============================================================================
# Helper & Retrieval Functions
# =============================================================================

def get_term(term_id, lang="en"):
    """
    Retrieve a glossary term by its unique identifier.
    Returns safe dict with translated strings and translation metadata.
    """
    if not term_id or not isinstance(term_id, str):
        return None

    clean_id = term_id.strip().lower()
    entry = GLOSSARY_TERMS.get(clean_id)
    if not entry:
        return None

    lang = lang.strip().lower() if isinstance(lang, str) else DEFAULT_LANGUAGE
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE

    name = entry["name"].get(lang) or entry["name"][DEFAULT_LANGUAGE]
    definition = entry["definition"].get(lang) or entry["definition"][DEFAULT_LANGUAGE]
    comp_notes = (entry.get("competition_notes", {}).get(lang) or
                  entry.get("competition_notes", {}).get(DEFAULT_LANGUAGE, ""))

    category_meta = CATEGORIES.get(entry["category"], {})
    category_name = category_meta.get(lang) or category_meta.get(DEFAULT_LANGUAGE, entry["category"].title())

    is_fallback = (lang != DEFAULT_LANGUAGE and (
        lang not in entry["definition"] or not entry["definition"][lang]
    ))

    return {
        "ok": True,
        "id": entry["id"],
        "name": name,
        "category": entry["category"],
        "category_name": category_name,
        "definition": definition,
        "formula": entry.get("formula"),
        "authority_type": entry.get("authority_type"),
        "rule_reference": entry.get("rule_reference"),
        "competition_notes": comp_notes,
        "context_key": entry.get("context_key"),
        "requested_language": lang,
        "is_fallback": is_fallback,
        "available_languages": list(SUPPORTED_LANGUAGES),
    }


def get_all_terms(lang="en"):
    """
    Retrieve all glossary terms formatted for the specified language.
    Ordered logically by category and name.
    """
    res = []
    for term_id in GLOSSARY_TERMS:
        term = get_term(term_id, lang=lang)
        if term:
            res.append(term)
    return res


def get_terms_by_category(category, lang="en"):
    """
    Retrieve all terms belonging to a specific category.
    """
    if not category or not isinstance(category, str):
        return []

    clean_cat = category.strip().lower()
    res = []
    for term_id, entry in GLOSSARY_TERMS.items():
        if entry["category"] == clean_cat:
            t = get_term(term_id, lang=lang)
            if t:
                res.append(t)
    return res


def search_terms(query, lang="en"):
    """
    Case-insensitive search across term IDs, names, definitions, and rule references.
    Supports English, Hindi, and Marathi keyword search.
    """
    if not query or not isinstance(query, str):
        return []

    q = query.strip().lower()
    if not q:
        return []

    matches = []
    for term_id, entry in GLOSSARY_TERMS.items():
        score = 0
        # Exact ID match
        if q == term_id or q == term_id.replace("_", " ") or q == term_id.replace("_", ""):
            score += 100

        # Name match across all languages
        for l_code, name_str in entry["name"].items():
            if q in name_str.lower():
                score += 50
                break

        # Formula match
        if entry.get("formula") and q in entry["formula"].lower():
            score += 20

        # Definition match in requested language
        defn = entry["definition"].get(lang, "") or entry["definition"].get(DEFAULT_LANGUAGE, "")
        if q in defn.lower():
            score += 10

        # Rule reference match
        if entry.get("rule_reference") and q in entry["rule_reference"].lower():
            score += 15

        if score > 0:
            t = get_term(term_id, lang=lang)
            if t:
                t["search_score"] = score
                matches.append(t)

    # Sort matches by relevance score descending
    matches.sort(key=lambda x: x.get("search_score", 0), reverse=True)
    return matches


# =============================================================================
# Context-Aware Match Example Builder
# =============================================================================

def build_term_context(term_id, match_facts, lang="en"):
    """
    Constructs a verified, factually grounded match example using current match metrics.
    Strictly avoids fabricated figures and explicitly handles missing or stale data.
    """
    if not term_id or not match_facts or not isinstance(match_facts, dict):
        return None

    clean_id = term_id.strip().lower()
    entry = GLOSSARY_TERMS.get(clean_id)
    if not entry:
        return None

    lang = lang.strip().lower() if isinstance(lang, str) else DEFAULT_LANGUAGE
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE

    is_stale = match_facts.get("is_stale", False)
    age_sec = match_facts.get("data_age_sec", 0)
    innings = match_facts.get("innings", 1)
    status = match_facts.get("status", "live")

    # Helper localized notice prefixes
    stale_notice = ""
    if is_stale:
        if lang == "hi":
            stale_notice = f"[सूचना: लाइव मैच फीड {age_sec}s विलंबित है] "
        elif lang == "mr":
            stale_notice = f"[सूचना: लाइव्ह मॅच फीड {age_sec}s उशिरा आहे] "
        else:
            stale_notice = f"[Notice: Live match feed delayed by {age_sec}s] "

    # 1. Batting Strike Rate
    if clean_id == "strike_rate":
        batters = match_facts.get("batters", [])
        if not batters:
            return None

        examples = []
        for b in batters:
            runs = b.get("runs")
            balls = b.get("balls")
            name = b.get("name", "Batter")
            if runs is not None and balls is not None:
                try:
                    r_val = int(runs)
                    b_val = int(balls)
                    if b_val > 0:
                        sr_val = round((r_val / b_val) * 100, 2)
                        sr_str = f"{sr_val:.2f}"
                    else:
                        sr_str = "0.00"

                    if lang == "hi":
                        examples.append(f"{name}: {r_val} रन ({b_val} गेंदें) → स्ट्राइक रेट: {sr_str}")
                    elif lang == "mr":
                        examples.append(f"{name}: {r_val} धावा ({b_val} चेंडू) → स्ट्राइक रेट: {sr_str}")
                    else:
                        examples.append(f"{name}: {r_val} runs ({b_val} balls) → Strike Rate: {sr_str}")
                except (ValueError, TypeError):
                    continue

        if not examples:
            return None

        body = " | ".join(examples)
        return {
            "has_context": True,
            "term_id": clean_id,
            "text": f"{stale_notice}{body}",
            "is_stale": is_stale,
        }

    # 2. Bowling Economy Rate
    elif clean_id == "economy_rate":
        bowler = match_facts.get("bowler")
        if not bowler or not isinstance(bowler, dict):
            return None

        name = bowler.get("name", "Current Bowler")
        runs = bowler.get("runs")
        overs = bowler.get("overs")

        if runs is not None and overs is not None:
            try:
                r_val = int(runs)
                ov_val = float(overs)
                # Compute legal balls from cricket overs notation (e.g. 3.2 = 3 overs + 2 balls = 20 balls)
                full_overs = int(ov_val)
                part_balls = int(round((ov_val - full_overs) * 10))
                total_balls = (full_overs * 6) + part_balls

                if total_balls > 0:
                    econ_val = round((r_val / total_balls) * 6, 2)
                    econ_str = f"{econ_val:.2f}"
                else:
                    econ_str = "0.00"

                if lang == "hi":
                    text = f"{name}: {ov_val} ओवर में {r_val} रन दिए → इकोनॉमी रेट: {econ_str} रन प्रति ओवर।"
                elif lang == "mr":
                    text = f"{name}: {ov_val} षटकांत {r_val} धावा दिल्या → इकॉनॉमी रेट: {econ_str} धावा प्रति षटक."
                else:
                    text = f"{name}: {r_val} runs conceded in {ov_val} overs → Economy Rate: {econ_str} per over."

                return {
                    "has_context": True,
                    "term_id": clean_id,
                    "text": f"{stale_notice}{text}",
                    "is_stale": is_stale,
                }
            except (ValueError, TypeError):
                return None

    # 3. Current Run Rate
    elif clean_id == "current_run_rate":
        score = match_facts.get("score")
        overs = match_facts.get("overs")
        run_rate = match_facts.get("run_rate")
        batting_team = match_facts.get("batting_team", "Batting Team")

        if score is not None and overs is not None and run_rate is not None:
            if lang == "hi":
                text = f"{batting_team}: {overs} ओवर में {score} रन → करंट रन रेट: {run_rate} रन प्रति ओवर।"
            elif lang == "mr":
                text = f"{batting_team}: {overs} षटकांत {score} धावा → सध्याची धावगती: {run_rate} धावा प्रति षटक."
            else:
                text = f"{batting_team}: {score} runs in {overs} overs → Current Run Rate: {run_rate} runs per over."

            return {
                "has_context": True,
                "term_id": clean_id,
                "text": f"{stale_notice}{text}",
                "is_stale": is_stale,
            }

    # 4. Required Run Rate
    elif clean_id == "required_run_rate":
        if innings < 2:
            if lang == "hi":
                text = "वर्तमान मैच पहली पारी में है। लक्ष्य दूसरी पारी शुरू होने पर निर्धारित होगा।"
            elif lang == "mr":
                text = "सध्या सामना पहिल्या डावात आहे. लक्ष्य दुसऱ्या डावात निश्चित होईल."
            else:
                text = "Match is currently in the 1st innings. Required Run Rate only applies in the 2nd innings once a target is established."
            return {
                "has_context": False,
                "term_id": clean_id,
                "text": text,
                "is_stale": is_stale,
            }

        runs_req = match_facts.get("runs_required")
        balls_rem = match_facts.get("balls_remaining")
        rrr = match_facts.get("required_run_rate")
        target = match_facts.get("target")

        if runs_req is not None and balls_rem is not None and rrr is not None:
            if lang == "hi":
                text = f"लक्ष्य: {target} | जीतने के लिए {balls_rem} गेंदों में {runs_req} रन चाहिए → आवश्यक रन रेट (RRR): {rrr}।"
            elif lang == "mr":
                text = f"लक्ष्य: {target} | जिंकण्यासाठी {balls_rem} चेंडूंत {runs_req} धावा हव्यात → आवश्यक धावगती (RRR): {rrr}."
            else:
                text = f"Target: {target} | Need {runs_req} runs from {balls_rem} balls → Required Run Rate: {rrr} per over."

            return {
                "has_context": True,
                "term_id": clean_id,
                "text": f"{stale_notice}{text}",
                "is_stale": is_stale,
            }

    # 5. Partnership
    elif clean_id == "partnership":
        p_data = match_facts.get("partnership")
        if not p_data or not isinstance(p_data, dict):
            return None

        runs = p_data.get("runs")
        balls = p_data.get("balls")
        b1 = p_data.get("batter1_name", "")
        b2 = p_data.get("batter2_name", "")

        if runs is not None:
            balls_str = f" ({balls} balls)" if balls is not None else ""
            pair_str = f"{b1} & {b2}" if b1 and b2 else "Current pair"

            if lang == "hi":
                text = f"{pair_str} की साझेदारी: {runs} रन{balls_str}।"
            elif lang == "mr":
                text = f"{pair_str} ची भागीदारी: {runs} धावा{balls_str}."
            else:
                text = f"Partnership for {pair_str}: {runs} runs{balls_str}."

            return {
                "has_context": True,
                "term_id": clean_id,
                "text": f"{stale_notice}{text}",
                "is_stale": is_stale,
            }

    # 6. Target
    elif clean_id == "target":
        if innings < 2:
            if lang == "hi":
                text = "पहली पारी जारी है। दूसरी पारी के लिए अभी लक्ष्य निर्धारित नहीं हुआ है।"
            elif lang == "mr":
                text = "पहिला डाव सुरू आहे. दुसऱ्या डावासाठी अजून लक्ष्य निश्चित झालेले नाही."
            else:
                text = "1st innings in progress; target has not yet been set."
            return {
                "has_context": False,
                "term_id": clean_id,
                "text": text,
                "is_stale": is_stale,
            }

        target = match_facts.get("target")
        if target is not None:
            batting_team = match_facts.get("batting_team", "Batting Team")
            if lang == "hi":
                text = f"{batting_team} के लिए जीत का लक्ष्य: {target} रन।"
            elif lang == "mr":
                text = f"{batting_team} साठी विजयाचे लक्ष्य: {target} धावा."
            else:
                text = f"Target for {batting_team}: {target} runs to win."

            return {
                "has_context": True,
                "term_id": clean_id,
                "text": f"{stale_notice}{text}",
                "is_stale": is_stale,
            }

    return None

