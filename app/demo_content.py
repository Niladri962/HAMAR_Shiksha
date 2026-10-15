"""Small curriculum bank used ONLY by the demonstration seed.

Questions are simple, self-written practice items for illustration; they are
not official SCERT material. In a real deployment, learning content is loaded
from approved sources and marked approved by an authorised reviewer.
"""

# (subject_code, band) -> topic -> {"difficulty", "lesson", "questions"}
# band: "primary" (classes 1-5) or "middle" (classes 6-8)
BANK: dict[tuple[str, str], dict[str, dict]] = {
    ("MATH", "primary"): {
        "Fractions": {
            "difficulty": 0.32,
            "lesson": ("A fraction shows part of a whole. In 3/4, the bottom number (4) tells how many equal "
                       "parts the whole is divided into, and the top number (3) tells how many parts we take. "
                       "Example: a roti cut into 4 equal pieces - if you eat 3 pieces, you ate 3/4 of the roti. "
                       "Fractions with the same bottom number are compared by their top numbers: 3/4 > 1/4."),
            "questions": [
                ("Which fraction is bigger?", ["1/4", "3/4", "They are equal", "Cannot say"], 1),
                ("A mango is cut into 8 equal pieces. Ravi eats 3. What fraction did he eat?",
                 ["3/5", "5/8", "3/8", "8/3"], 2),
                ("What is 1/2 + 1/2?", ["1", "2/4", "1/4", "2"], 0),
                ("Which fraction equals 2/4?", ["1/4", "1/2", "2/3", "3/4"], 1),
                ("Which is bigger: 1/3 or 1/5?", ["1/3", "1/5", "They are equal", "Cannot say"], 0),
            ],
        },
        "Place value": {
            "difficulty": 0.05,
            "lesson": ("In 4,352 the digit 4 is in the thousands place (4,000), 3 in hundreds (300), 5 in "
                       "tens (50) and 2 in ones (2). Expanded form: 4000 + 300 + 50 + 2."),
            "questions": [
                ("What is the place value of 7 in 5,742?", ["7", "70", "700", "7000"], 2),
                ("Which number is 3000 + 400 + 5?", ["3405", "3045", "3450", "34005"], 0),
                ("Which is the largest number?", ["9,099", "9,909", "9,990", "9,009"], 2),
            ],
        },
        "Measurement": {
            "difficulty": 0.12,
            "lesson": ("1 metre = 100 centimetres and 1 kilometre = 1000 metres. 1 kilogram = 1000 grams. "
                       "1 litre = 1000 millilitres. To change metres to centimetres, multiply by 100."),
            "questions": [
                ("How many centimetres are in 2 metres?", ["20", "200", "2000", "100"], 1),
                ("1 kilogram equals how many grams?", ["10", "100", "1000", "10000"], 2),
                ("Which unit is best to measure water in a bucket?", ["Kilometre", "Litre", "Gram", "Centimetre"], 1),
            ],
        },
    },
    ("EVS", "primary"): {
        "Water": {
            "difficulty": 0.05,
            "lesson": ("We get water from rain, rivers, ponds and wells. Rainwater can be saved by collecting it "
                       "from rooftops (rainwater harvesting). Boiling or filtering water makes it safe to drink."),
            "questions": [
                ("Which is a way to save rainwater?", ["Rooftop harvesting", "Leaving taps open",
                                                       "Throwing waste in ponds", "Cutting trees"], 0),
                ("How can we make water safe to drink at home?", ["Add salt", "Boil it", "Freeze it", "Shake it"], 1),
                ("Which of these is NOT a source of water?", ["Well", "River", "Rain", "Stone"], 3),
            ],
        },
        "Plants and seeds": {
            "difficulty": 0.1,
            "lesson": ("Seeds need water, air and warmth to sprout (germinate). Some seeds are spread by wind, "
                       "some by water and some by animals. Rice is the main crop of Chhattisgarh, often called "
                       "the 'rice bowl of India'."),
            "questions": [
                ("What does a seed need to sprout?", ["Only soil", "Water, air and warmth", "Darkness only",
                                                      "Salt"], 1),
                ("Which crop is Chhattisgarh famous for?", ["Tea", "Apple", "Rice", "Coffee"], 2),
                ("How are cotton seeds mostly spread?", ["By wind", "By fire", "By stones", "They are not spread"], 0),
            ],
        },
    },
    ("HIN", "primary"): {
        "संज्ञा": {
            "difficulty": 0.08,
            "lesson": ("किसी व्यक्ति, वस्तु, स्थान या भाव के नाम को संज्ञा कहते हैं। जैसे - राम, किताब, रायपुर, "
                       "खुशी। संज्ञा के तीन मुख्य भेद हैं: व्यक्तिवाचक, जातिवाचक और भाववाचक।"),
            "questions": [
                ("इनमें से संज्ञा शब्द कौन सा है?", ["दौड़ना", "सुंदर", "रायपुर", "धीरे"], 2),
                ("'खुशी' कौन सी संज्ञा है?", ["व्यक्तिवाचक", "जातिवाचक", "भाववाचक", "यह संज्ञा नहीं है"], 2),
                ("'नदी' शब्द कौन सी संज्ञा है?", ["जातिवाचक", "व्यक्तिवाचक", "भाववाचक", "क्रिया"], 0),
            ],
        },
        "विलोम शब्द": {
            "difficulty": 0.04,
            "lesson": "विलोम शब्द का अर्थ है उल्टा अर्थ बताने वाला शब्द। जैसे - दिन-रात, सुख-दुख, ऊपर-नीचे।",
            "questions": [
                ("'दिन' का विलोम शब्द क्या है?", ["सुबह", "रात", "शाम", "सूरज"], 1),
                ("'सुख' का विलोम शब्द क्या है?", ["दुख", "खुशी", "आनंद", "हँसी"], 0),
                ("'ऊपर' का विलोम क्या है?", ["आगे", "पीछे", "नीचे", "बाहर"], 2),
            ],
        },
    },
    ("ENG", "primary"): {
        "Nouns": {
            "difficulty": 0.12,
            "lesson": ("A noun is a naming word: the name of a person, place, animal or thing. Examples: Meena, "
                       "Bilaspur, cow, book. Proper nouns (Meena, Bilaspur) begin with a capital letter."),
            "questions": [
                ("Which word is a noun?", ["run", "happy", "school", "quickly"], 2),
                ("Which is a proper noun?", ["city", "river", "Mahanadi", "girl"], 2),
                ("Find the noun: 'The cow eats grass.'", ["eats", "the", "cow", "green"], 2),
            ],
        },
        "Opposites": {
            "difficulty": 0.06,
            "lesson": "Opposites are words with opposite meanings: big - small, hot - cold, open - close.",
            "questions": [
                ("Opposite of 'hot'?", ["warm", "cold", "sunny", "big"], 1),
                ("Opposite of 'open'?", ["close", "door", "wide", "push"], 0),
                ("Opposite of 'tall'?", ["long", "high", "short", "thin"], 2),
            ],
        },
    },
    ("MATH", "middle"): {
        "Linear equations": {
            "difficulty": 0.24,
            "lesson": ("A linear equation has a variable with power 1, e.g. 2x + 3 = 11. To solve, do the same "
                       "operation on both sides: 2x + 3 - 3 = 11 - 3 gives 2x = 8, then divide both sides by 2: "
                       "x = 4. Always check by substituting back: 2(4) + 3 = 11."),
            "questions": [
                ("Solve: x + 7 = 15", ["x = 22", "x = 8", "x = 7", "x = -8"], 1),
                ("Solve: 3x = 21", ["x = 7", "x = 18", "x = 24", "x = 63"], 0),
                ("Solve: 2x - 5 = 9", ["x = 2", "x = 7", "x = 4", "x = 14"], 1),
                ("If 5 notebooks cost Rs 150, what is the cost of one (5x = 150)?",
                 ["Rs 25", "Rs 30", "Rs 35", "Rs 750"], 1),
            ],
        },
        "Rational numbers": {
            "difficulty": 0.16,
            "lesson": ("A rational number can be written as p/q where p and q are integers and q is not 0. "
                       "Examples: 1/2, -3/4, 5 (= 5/1). The additive inverse of 2/3 is -2/3."),
            "questions": [
                ("Which is NOT a rational number?", ["1/2", "-3", "5/0", "0"], 2),
                ("Additive inverse of 3/5 is", ["5/3", "-3/5", "3/5", "-5/3"], 1),
                ("1/2 + 1/3 =", ["2/5", "5/6", "1/6", "2/6"], 1),
            ],
        },
    },
    ("SCI", "middle"): {
        "Crop production": {
            "difficulty": 0.08,
            "lesson": ("Kharif crops (like paddy) are sown in the rainy season (June-July); rabi crops (like wheat, "
                       "gram) are sown in winter (October-November). Steps: preparing soil, sowing, adding manure, "
                       "irrigation, weeding, harvesting and storage."),
            "questions": [
                ("Paddy is a ___ crop.", ["Rabi", "Kharif", "Zaid", "Cash only"], 1),
                ("Removing unwanted plants from a field is called", ["Sowing", "Weeding", "Harvesting",
                                                                    "Threshing"], 1),
                ("Which adds organic matter to soil?", ["Plastic", "Manure", "Sand", "Salt"], 1),
            ],
        },
        "Force and pressure": {
            "difficulty": 0.18,
            "lesson": ("A force is a push or a pull. Pressure = force / area, so the same force on a smaller area "
                       "gives more pressure. That is why knives are sharp and school bags have wide straps."),
            "questions": [
                ("Pressure equals", ["force x area", "force / area", "area / force", "force + area"], 1),
                ("Why are bag straps made wide?", ["To look nice", "To reduce pressure on shoulders",
                                                   "To increase force", "To make bags heavier"], 1),
                ("Opening a door is an example of", ["Only push", "Only pull", "Push or pull - a force",
                                                     "No force"], 2),
            ],
        },
    },
    ("HIN", "middle"): {
        "पर्यायवाची शब्द": {
            "difficulty": 0.07,
            "lesson": "समान अर्थ वाले शब्दों को पर्यायवाची कहते हैं। जैसे - पानी: जल, नीर; सूरज: सूर्य, रवि।",
            "questions": [
                ("'जल' का पर्यायवाची क्या है?", ["आग", "नीर", "हवा", "धरती"], 1),
                ("'सूर्य' का पर्यायवाची क्या है?", ["चंद्र", "रवि", "तारा", "आकाश"], 1),
                ("'पेड़' का पर्यायवाची क्या है?", ["वृक्ष", "फूल", "पत्ता", "जड़"], 0),
            ],
        },
    },
    ("ENG", "middle"): {
        "Tenses": {
            "difficulty": 0.15,
            "lesson": ("Present: I play. Past: I played. Future: I will play. Words like 'yesterday' point to "
                       "the past; 'tomorrow' points to the future."),
            "questions": [
                ("Yesterday she ___ to school.", ["go", "goes", "went", "will go"], 2),
                ("Tomorrow we ___ the match.", ["played", "will play", "plays", "playing"], 1),
                ("He ___ football every day.", ["play", "plays", "played", "will played"], 1),
            ],
        },
    },
    ("SST", "middle"): {
        "Resources": {
            "difficulty": 0.1,
            "lesson": ("Anything that can meet a need is a resource. Renewable resources (sunlight, water, forests "
                       "if managed well) can be replenished; non-renewable ones (coal, petroleum) cannot. "
                       "Chhattisgarh is rich in forests and minerals such as coal and iron ore."),
            "questions": [
                ("Which is a non-renewable resource?", ["Sunlight", "Wind", "Coal", "Water"], 2),
                ("Chhattisgarh is rich in which mineral?", ["Iron ore", "Gold only", "Diamonds only",
                                                            "Petroleum only"], 0),
                ("Using resources carefully is called", ["Wasting", "Conservation", "Pollution", "Mining"], 1),
            ],
        },
    },
}

SUBJECTS_BY_BAND = {
    "primary": ["HIN", "ENG", "MATH", "EVS"],
    "middle": ["HIN", "ENG", "MATH", "SCI", "SST"],
}


def band(grade: int) -> str:
    return "primary" if grade <= 5 else "middle"


def lo_code(subject_code: str, grade: int, topic: str) -> str:
    topics = list(BANK[(subject_code, band(grade))])
    return f"DEMO-{subject_code}{grade}.{topics.index(topic) + 1}"


def questions_for(subject_code: str, grade: int, topic: str) -> list[dict]:
    t = BANK[(subject_code, band(grade))][topic]
    code = lo_code(subject_code, grade, topic)
    return [{"id": f"q{i + 1}", "qtype": "mcq", "text": q, "options": opts, "answer_index": ans, "topic": topic,
             "lo": code, "max_marks": 1.0, "misconceptions": MISCONCEPTIONS.get(q, {})}
            for i, (q, opts, ans) in enumerate(t["questions"])]


# Learning-outcome statements for the demo topics: (chapter title, description, Hindi description).
LO_TEXT = {
    "Place value": ("Chapter 1: Place Value", "Reads and writes 4-digit numbers using place value and expanded form.",
                    "स्थानीय मान और विस्तारित रूप से 4 अंकों की संख्याएँ पढ़ता-लिखता है।"),
    "Fractions": ("Chapter 2: Fractions", "Represents, compares and adds fractions with like denominators.",
                  "समान हर वाली भिन्नों को दर्शाता, तुलना करता और जोड़ता है।"),
    "Measurement": ("Chapter 3: Measurement", "Converts between standard units of length, mass and capacity.",
                    "लंबाई, भार और धारिता की मानक इकाइयों में रूपांतरण करता है।"),
    "Water": ("Chapter 1: Water", "Identifies sources of water and ways to keep it safe and save it.",
              "जल के स्रोत पहचानता है और जल को सुरक्षित रखने व बचाने के उपाय बताता है।"),
    "Plants and seeds": ("Chapter 2: Plants and Seeds", "Explains conditions for germination and seed dispersal.",
                         "अंकुरण की परिस्थितियाँ और बीजों के फैलाव को समझाता है।"),
    "संज्ञा": ("अध्याय 1: संज्ञा", "Identifies nouns and their three main types.", "संज्ञा और उसके तीन मुख्य भेद पहचानता है।"),
    "विलोम शब्द": ("अध्याय 2: विलोम शब्द", "Uses antonyms correctly.", "विलोम शब्दों का सही प्रयोग करता है।"),
    "Nouns": ("Unit 1: Nouns", "Identifies common and proper nouns in sentences.", "वाक्यों में जातिवाचक व व्यक्तिवाचक संज्ञा पहचानता है।"),
    "Opposites": ("Unit 2: Opposites", "Uses opposite words in context.", "संदर्भ में विपरीतार्थक शब्दों का प्रयोग करता है।"),
    "Linear equations": ("Chapter 2: Linear Equations in One Variable",
                         "Solves linear equations in one variable and word problems.",
                         "एक चर वाले रैखिक समीकरण और शाब्दिक प्रश्न हल करता है।"),
    "Rational numbers": ("Chapter 1: Rational Numbers", "Identifies rational numbers, inverses and adds them.",
                         "परिमेय संख्याएँ, व्युत्क्रम पहचानता और उन्हें जोड़ता है।"),
    "Crop production": ("Chapter 1: Crop Production and Management",
                        "Describes kharif/rabi crops and steps of crop production.",
                        "खरीफ/रबी फसलें और फसल उत्पादन के चरण बताता है।"),
    "Force and pressure": ("Chapter 2: Force and Pressure", "Relates force, area and pressure in daily life.",
                           "दैनिक जीवन में बल, क्षेत्रफल और दाब का संबंध समझाता है।"),
    "पर्यायवाची शब्द": ("अध्याय 1: पर्यायवाची शब्द", "Uses synonyms correctly.", "पर्यायवाची शब्दों का सही प्रयोग करता है।"),
    "Tenses": ("Unit 3: Tenses", "Uses present, past and future tense correctly.", "वर्तमान, भूत और भविष्य काल का सही प्रयोग करता है।"),
    "Resources": ("Chapter 1: Resources", "Classifies resources and explains conservation.", "संसाधनों का वर्गीकरण कर संरक्षण समझाता है।"),
}

MISCONCEPTIONS = {
    "Which is bigger: 1/3 or 1/5?": {"1": "Whole-number bias: thinks a larger denominator means a larger fraction."},
    "Which fraction is bigger?": {"0": "Compares denominators instead of numerators for like fractions."},
    "Solve: x + 7 = 15": {"0": "Adds instead of subtracting when moving a term across the equals sign."},
    "Solve: 2x - 5 = 9": {"0": "Subtracts 5 instead of adding it when transposing."},
    "Pressure equals": {"0": "Confuses pressure with force multiplied by area."},
    "What is the place value of 7 in 5,742?": {"0": "Confuses face value with place value."},
}

# (subject, band, topic, text, accepted answers, difficulty)
SHORT_QUESTIONS = [
    ("MATH", "primary", "Fractions", "Write the fraction for 3 out of 8 equal parts.", ["3/8"], 1),
    ("MATH", "primary", "Fractions", "What is 1/5 + 2/5?", ["3/5"], 2),
    ("MATH", "primary", "Fractions", "Which is bigger, 2/7 or 2/9? Write the fraction.", ["2/7"], 3),
    ("MATH", "primary", "Measurement", "How many centimetres are there in 3 metres?", ["300", "300 cm", "300 centimetres"], 1),
    ("MATH", "primary", "Place value", "Write the place value of 6 in 6,215.", ["6000", "6,000"], 1),
    ("MATH", "middle", "Linear equations", "Solve for x: 3x + 4 = 19", ["5", "x=5", "x = 5"], 2),
    ("MATH", "middle", "Linear equations", "Solve for x: 4x - 6 = 18", ["6", "x=6", "x = 6"], 3),
    ("MATH", "middle", "Rational numbers", "Write the additive inverse of 2/7.", ["-2/7"], 2),
    ("SCI", "middle", "Force and pressure", "Write the formula for pressure.",
     ["force/area", "pressure = force/area", "force divided by area", "pressure=force/area"], 2),
]
# (subject, band, topic, text, rubric, max marks)
DESCRIPTIVE_QUESTIONS = [
    ("SCI", "middle", "Crop production", "Explain any two steps of crop production in your own words.",
     "1 mark for each correctly named and explained step (soil preparation, sowing, manuring, irrigation, weeding, "
     "harvesting, storage).", 2),
    ("EVS", "primary", "Water", "Write two ways your family can save water at home.",
     "1 mark for each sensible way (closing taps, reusing water, fixing leaks, rainwater harvesting).", 2),
]

TRAINING = [
    {"code": "DEMO-TM-MATH-01", "title": "Teaching fractions with concrete materials",
     "title_hi": "ठोस सामग्री से भिन्न पढ़ाना", "subject": "MATH", "area": "Mathematics pedagogy", "minutes": 15,
     "sections": [
         {"heading": "Why concrete first", "body": "Children understand 'equal parts' before symbols. Start with rotis, "
          "paper strips or leaves cut into equal parts, then move to drawings, then to the notation 3/4."},
         {"heading": "Tackling whole-number bias", "body": "Many learners think 1/5 > 1/3 because 5 > 3. Fold two equal "
          "paper strips into 3 and 5 parts and compare one part of each."},
         {"heading": "Quick classroom check", "body": "Ask: 'Which piece would you choose, 1/3 or 1/5 of a laddoo?' and "
          "ask learners to justify with a drawing."}],
     "check": [{"q": "Which activity best addresses whole-number bias?", "options": [
         "Memorising rules", "Comparing folded strips of equal length", "Copying fractions from the board"], "answer": 1},
         {"q": "What should come first when introducing fractions?", "options": [
             "Symbols", "Concrete equal sharing", "Long division"], "answer": 1}]},
    {"code": "DEMO-TM-SCI-01", "title": "Activity-based science with local materials",
     "title_hi": "स्थानीय सामग्री से गतिविधि-आधारित विज्ञान", "subject": "SCI", "area": "Science pedagogy", "minutes": 20,
     "sections": [
         {"heading": "Predict - observe - explain", "body": "Ask learners to predict, do a simple activity (e.g. pressing a "
          "pin and a thumb into clay), observe, then explain using the idea of pressure = force / area."},
         {"heading": "Use the farm", "body": "Most learners know kharif and rabi crops from home. Start crop production "
          "lessons from their own family's farming calendar."}],
     "check": [{"q": "In predict-observe-explain, what comes first?", "options": ["Explain", "Observe", "Predict"], "answer": 2}]},
    {"code": "DEMO-TM-EVS-01", "title": "Learning from the local environment",
     "title_hi": "स्थानीय पर्यावरण से सीखना", "subject": "EVS", "area": "EVS pedagogy", "minutes": 15,
     "sections": [{"heading": "Village walks", "body": "Plan a 20-minute walk to the school's water source; learners "
                   "record observations and discuss how to keep water safe."}],
     "check": [{"q": "A village walk is mainly for...", "options": ["Discipline", "Observation and inquiry", "Exercise"], "answer": 1}]},
    {"code": "DEMO-TM-GEN-01", "title": "Multilingual classroom strategies",
     "title_hi": "बहुभाषी कक्षा की रणनीतियाँ", "subject": None, "area": "Inclusive teaching", "minutes": 15,
     "sections": [{"heading": "Bridge from home language", "body": "Allow learners to explain ideas first in Chhattisgarhi, "
                   "Gondi or Halbi, then build the Hindi/English academic words alongside."}],
     "check": [{"q": "Allowing home-language explanation helps learners to...", "options": [
         "Avoid Hindi", "Connect ideas to new academic vocabulary", "Finish faster"], "answer": 1}]},
]


FIRST_NAMES = ["Aarti", "Bhavna", "Chandan", "Deepak", "Gita", "Hemant", "Ishita", "Jyoti", "Kiran", "Lata",
               "Manoj", "Neha", "Omkar", "Pooja", "Rahul", "Sangeeta", "Tarun", "Usha", "Vikas", "Yamini",
               "Anil", "Barkha", "Dinesh", "Komal", "Mohan", "Payal", "Rakesh", "Sunita", "Tulsi", "Vinod"]
LAST_NAMES = ["Sahu", "Verma", "Patel", "Netam", "Markam", "Yadav", "Dhruw", "Sinha", "Kashyap", "Thakur",
              "Mandavi", "Nishad", "Kanwar", "Sori", "Chandrakar"]
