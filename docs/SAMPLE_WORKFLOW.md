# Sample curriculum-grounded workflow (real run)

- Date: 2026-10-14 11:19 UTC
- Gyan SLM: `llama3.2:3b` via local Ollama · retrieval: BAAI/bge-m3
- Data: demonstration seed + demo primers (**not SCERT material**).
- Every block below is the actual API response from this run (trimmed for length).

## 1. Teacher Saathi - academic plan summary (deterministic)

```json
{
 "summary": {
  "planned_due": 8,
  "taught": 5,
  "assessed": 5,
  "learned": 4,
  "taught_rate": 0.625,
  "learned_rate": 0.8,
  "basis": "8 outcomes scheduled up to 2026-10-14 in 1 class-subjects"
 },
 "first_milestones": [
  {
   "id": 5,
   "week": "2026-06-15",
   "code": "DEMO-MATH5.1",
   "chapter": "Chapter 2: Fractions",
   "topic": "Fractions",
   "description": "Represents, compares and adds fractions with like denominators.",
   "description_hi": "समान हर वाली भिन्नों को दर्शाता, तुलना करता और जोड़ता है।",
   "status": "taught",
   "taught_at": "2026-06-18T12:00:00",
   "overdue": false,
   "learned": {
    "avg_mastery": 0.3917,
    "students_assessed": 12,
    "learned": false
   },
   "lesson_plan_id": null
  },
  {
   "id": 6,
   "week": "2026-09-07",
   "code": "DEMO-MATH5.2",
   "chapter": "Chapter 1: Place Value",
   "topic": "Place value",
   "description": "Reads and writes 4-digit numbers using place value and expanded form.",
   "description_hi": "स्थानीय मान और विस्तारित रूप से 4 अंकों की संख्याएँ पढ़ता-लिखता है।",
   "status": "taught",
   "taught_at": "2026-09-10T12:00:00",
   "overdue": false,
   "learned": {
    "avg_mastery": 0.7,
    "students_assessed": 10,
    "learned": true
   },
   "lesson_plan_id": null
  },
  {
   "id": 7,
   "week": "2026-11-30",
   "code": "DEMO-MATH5.3",
   "chapter": "Chapter 3: Measurement",
   "topic": "Measurement",
   "description": "Converts between standard units of length, mass and capacity.",
   "description_hi": "लंबाई, भार और धारिता की मानक इकाइयों में रूपांतरण करता है।",
   "status": "planned",
   "taught_at": null,
   "overdue": false,
   "learned": {
    "avg_mastery": 0.6667,
    "students_assessed": 11,
    "learned": true
   },
   "lesson_plan_id": null
  }
 ]
}
```

## 2. Lesson plan drafted by Gyan SLM (Hindi), grounded in textbook pages

```json
{
 "status": "draft",
 "ai_generated": true,
 "model": "llama3.2:3b",
 "title": "Fractions - Class 5-A",
 "body": "**विषय:** अंश (Fractions) - कक्षा 5 गणित\n**मूल्यांकन:** अंशों को प्रतिनिधित्व करना, तुलना करना और समान लघु संख्याओं वाले अंशों की जोड़ना\n**दिनांक:** [तारीख]\n**समय:** 40 मिनट\n\n**विद्यालय की योजना**\n\n**शिक्षा लक्ष्य**\n\n* छात्र अंशों को प्रतिनिधित्व कर सकेंगे।\n* छात्र अंशों को तुलना कर सकेंगे।\n* छात्र समान लघु संख्याओं वाले अंशों की जोड़ सकते हैं।\n\n**सामग्री (निम्न लागत वाली)**\n\n* पुस्तक \"डेमो प्राइमर: गणित कक्षा 5\" - [पृष्ठ 3, 4, 5]\n* कागज़ और पेन\n* अंशों के उदाहरण वाले सूत्र पत्रक\n\n**वार्म-अप (5 मिनट)**\n\n* छात्रों को अपने अंशों के बारे में सोचकर एक मिनट तक शांत रहें।\n* दूसरा मिनट, \"आपके लिए सबसे बड़ा अंश क्या है?\" पूछें।\n\n**व्याख्या और काम (10 मिनट)**\n\n* [सूत्र 3] से शुरू करें: \"एक अंश एक भाग होता है, जो एक पूरे से अलग है।\"\n* [सूत्र 4] से आगे बढ़ें: \"अंशों की तुलना करने के लिए, हमें उनके न्यूमेरेटर और डेनोमिनेटर को देखना होगा।\"\n* एक काम के साथ व्याख्या करें, जैसे [सूत्र 1] में दिया गया उदाहरण: \"एक मANGO को 8 समान भागों में काटा गया था, और रावी ने 3 भाग खाया।\"\n* छात्रों से पूछें: \"आपके लिए सबसे बड़ा अंश क्या है?\" और उनके उत्तरों को लिखें।\n\n**मार्गदर्शन (10 मिनट)**\n\n* [सूत्र 2] से आगे बढ़ें: \"अंशों की जोड़ने के लिए, हमें समान लघु संख्याओं वाले अंशों को जोड़ना होगा।\"\n* एक उदाहरण दें, जैसे [सूत्र 1] में दिया गया उदाहरण: \"एक मANGO को 8 समान भागों में काटा गया था, और रावी ने 3 भाग खाया।\"\n* छात्रों से पूछें: \"एक अंश जोड़ें, जैसे 1/5 + 2/5।\"\n\n**स्वतंत्र अभ्यास (10 मिनट)**\n\n* छात्रों को एक पत्रक पर अंशों की तुलना और जोड़ने के लिए दिया गया है।\n* उन्हें अपने उत्तर लिखने के लिए समय दें।\n\n**मूल्यांकन (3 प्रश्न)**\n\n1. यदि मैं 2/4 + 1/4 को जोड़ूं, तो मेरा उत्तर क्या होगा?\n2. यदि मैं 1/6 और 2/6 की तुलना करूं, तो मेरा निर्णय क्या होगा?\n3. यदि मैं 3/8 + 5/8 को जोड़ूं, तो मेरा उत्तर क्या होगा?\n\n**विशेषता (समर्थन / विस्तार)**\n\n* छात्रों के लिए अतिरिक्त चुनौतीपूर्ण उदाहरण प्रदान करें, जैसे [सूत्र 2] में दिया गया उदाहरण: \"3/4 और 1/4 की तुलना करें।\"\n* छात्रों को अपने अंशों को व्यवस्थित करने के लिए एक पत्रक प्रदान करें।\n* छात्रों को अपने अंशों के बारे में सोचकर एक मिनट तक शांत रहें, और उन्हें अपने उत्तर लिखने के लिए समय दें।",
 "sources": [
  {
   "chunk_id": 6,
   "text": "Demo Primer: Mathematics Class 5, Chapter 2: Fractions, p. 5",
   "document": "Demo Primer: Mathematics Class 5",
   "chapter": "Chapter 2: Fractions",
   "page": 5,
   "publisher": "DEMO (not SCERT)",
   "curriculum_version": 
...
```

## 3. Teacher approves the plan

```json
{
 "id": 3,
 "status": "approved"
}
```

## 4. Worksheet questions drafted (saved as DRAFT, invisible to students)

```json
{
 "drafts": [
  {
   "id": 125,
   "text": "What does the numerator of a fraction represent?",
   "options": [
    "The total number of parts the whole is divided into",
    "How many equal parts we take",
    "The size of each part",
    "The value of the whole"
   ],
   "correct_option": 1,
   "explanation": "It tells us how many of those equal parts we take."
  },
  {
   "id": 126,
   "text": "What type of fraction has a numerator smaller than its denominator?",
   "options": [
    "Proper fraction",
    "Improper fraction",
    "Equivalent fraction",
    "Similar fraction"
   ],
   "correct_option": 0,
   "explanation": "A proper fraction is less than one whole."
  },
  {
   "id": 127,
   "text": "When comparing fractions with the same denominator, which of the following is true?",
   "options": [
    "The fraction with the bigger numerator is smaller",
    "The fraction with the bigger numerator is larger",
    "The fraction with the bigger numerator is equal",
    "The fraction with the bigger numerator is undefined"
   ],
   "correct_option": 1,
   "explanation": "When the denominators are equal, the fraction with the bigger numerator is bigger."
  }
 ],
 "sources": [
  {
   "chunk_id": 4,
   "text": "Demo Primer: Mathematics Class 5, Chapter 2: Fractions, p. 3",
   "document": "Demo Primer: Mathematics Class 5",
   "chapter": "Chapter 2: Fractions",
   "page": 3,
   "publisher": "DEMO (not SCERT)",
   "curriculum_version": "DEMO-2026",
   "is_demo": true,
   "ref": "S1"
  },
  {
   "chunk_id": 6,
   "text": "Demo Primer: Mathematics Class 5, Chapter 2: Fractions, p. 5",
   "document": "Demo Primer: Mathematics Class 5",
   "chapter": "Chapter 2: Fractions",
   "page": 5,
   "publisher": "DEMO (not SCERT)",
   "curriculum_version": "DEMO-2026",
   "is_demo": true,
   "ref": "S2"
  },
  {
   "chunk_id": 5,
   "text": "Demo Primer: Mathematics Class 5, Chapter 2: Fractions, p. 4",
   "document": "Demo Primer: Mathematics Class 5",
   "chapter": "Chapter 2: Fractions",
   "page": 4,
   "publisher": "DEMO (not SCERT)",
   "curriculum_version": "DEMO-2026",
   "is_demo": true,
   "ref": "S3"
  },
  {
   "chunk_id": 9,
   "text": "डेमो पुस्तिका: गणित कक्षा 5, अध्याय 2: भिन्न, p. 1",
   "document": "डेमो पुस्तिका: गणित कक्षा 5",
   "chapter": "अध्याय 2: भिन्न",
   "page": 1,
   "publisher": "DEMO (not SCERT)",
   "curriculum_version": "DEMO-2026",
   "is_demo": true,
   "ref": "S4"
  }
 ],
 "notice": "Drafts are not visible to students. Check each answer 
...
```

## 5. Pariksha builds an assessment from approved bank questions

```json
{
 "id": 867,
 "questions": 5,
 "max_score": 5.0,
 "published": true
}
```

## 6. Student answers offline; the queued event syncs (second copy is a duplicate)

```json
{
 "results": [
  {
   "event_uid": "eba704f21b8347c08eec63a8d6d46ede",
   "status": "accepted",
   "detail": null
  },
  {
   "event_uid": "eba704f21b8347c08eec63a8d6d46ede",
   "status": "duplicate",
   "detail": "repeated in this batch"
  }
 ],
 "server_time": "2026-10-14T11:19:48.034596Z"
}
```

## 7. Uncertain short answers wait for the teacher (not auto-marked)

```json
[]
```

## 8. Learner record: competency + events (same record used by all modules)

```json
{
 "competencies": [
  {
   "code": "DEMO-MATH5.1",
   "subject": "Mathematics",
   "chapter": "Chapter 2: Fractions",
   "topic": "Fractions",
   "description": "Represents, compares and adds fractions with like denominators.",
   "description_hi": "समान हर वाली भिन्नों को दर्शाता, तुलना करता और जोड़ता है।",
   "mastery": 0.4,
   "correct": 6.0,
   "attempted": 15.0,
   "status": "needs_practice",
   "evidence": [
    "demo-res-3-8",
    "demo-res-15-8",
    "eba704f21b8347c08eec63a8d6d46ede"
   ]
  },
  {
   "code": "DEMO-MATH5.2",
   "subject": "Mathematics",
   "chapter": "Chapter 1: Place Value",
   "topic": "Place value",
   "description": "Reads and writes 4-digit numbers using place value and expanded form.",
   "description_hi": "स्थानीय मान और विस्तारित रूप से 4 अंकों की संख्याएँ पढ़ता-लिखता है।",
   "mastery": 0.6667,
   "correct": 2.0,
   "attempted": 3.0,
   "status": "developing",
   "evidence": [
    "demo-res-7-8"
   ]
  },
  {
   "code": "DEMO-MATH5.3",
   "subject": "Mathematics",
   "chapter": "Chapter 3: Measurement",
   "topic": "Measurement",
   "description": "Converts between standard units of length, mass and capacity.",
   "description_hi": "लंबाई, भार और धारिता की मानक इकाइयों में रूपांतरण करता है।",
   "mastery": 0.6667,
   "correct": 2.0,
   "attempted": 3.0,
   "status": "developing",
   "evidence": [
    "demo-res-11-8"
   ]
  }
 ],
 "latest_events": [
  {
   "uid": "eba704f21b8347c08eec63a8d6d46ede",
   "type": "assessment_result",
   "occurred_at": "2026-10-14T11:19:47.987323",
   "source": "sync",
   "summary": "Fractions check: 2/5"
  },
  {
   "uid": "demo-att-8-2026-10-14",
   "type": "attendance",
   "occurred_at": "2026-10-14T09:00:00",
   "source": "import",
   "summary": "Attendance 2026-10-14: present"
  },
  {
   "uid": "demo-att-8-2026-10-12",
   "type": "attendance",
   "occurred_at": "2026-10-12T09:00:00",
   "source": "import",
   "summary": "Attendance 2026-10-12: present"
  }
 ]
}
```

## 9. Teacher's weekly priority list with evidence

```json
{
 "week_of": "2026-10-12",
 "students": [
  {
   "student": "2fdeaa164504466d8939496bf8f5a9ec",
   "name": "Gita Sahu",
   "class_id": 1,
   "roll_no": 5,
   "needs": [
    {
     "code": "DEMO-EVS5.2",
     "subject": "Environmental Studies",
     "topic": "Plants and seeds",
     "description": "Explains conditions for germination and seed dispersal.",
     "mastery": 0.0,
     "evidence": "0 of 6 marks",
     "sources": [
      "Environmental Studies unit test - Plants and seeds: 0/3",
      "Environmental Studies unit test - Plants and seeds: 0/3"
     ]
    },
    {
     "code": "DEMO-MATH5.1",
     "subject": "Mathematics",
     "topic": "Fractions",
     "description": "Represents, compares and adds fractions with like denominators.",
     "mastery": 0.2,
     "evidence": "2 of 10 marks",
     "sources": [
      "Mathematics unit test - Fractions: 1/5",
      "Mathematics unit test - Fractions: 1/5"
     ]
    },
    {
     "code": "DEMO-MATH5.2",
     "subject": "Mathematics",
     "topic": "Place value",
     "description": "Reads and writes 4-digit numbers using place value and expanded form.",
     "mastery": 0.3333,
     "evidence": "1 of 3 marks",
     "sources": [
      "Mathematics unit test - Place value: 1/3"
     ]
    },
    {
     "code": "DEMO-EVS5.1",
     "subject": "Environmental Studies",
     "topic": "Water",
     "description": "Identifies sources of water and ways to keep it safe and save it.",
     "mastery": 0.5,
     "evidence": "3 of 6 marks",
     "sources": [
      "Environmental Studies unit test - Water: 2/3",
      "Environmental Studies unit test - Water: 1/3"
     ]
    }
   ],
   "priority_score": 2.967,
   "class": "Class 5-A"
  },
  {
   "student": "440d14bb149741d99fee4ad2b4d96537",
   "name": "Gita Kashyap",
   "class_id": 1,
   "roll_no": 6,
   "needs": [
    {
     "code": "DEMO-EVS5.2",
     "subject": "Environmental Studies",
     "topic": "Plants and seeds",
     "description": "Explains conditions for germination and seed dispersal.",
     "mastery": 0.1667,
     "evidence": "1 of 6 marks",
     "sources": [
      "Environmental Studies unit test - Plants and seeds: 1/3",
      "Environmental Studies unit test - Plants and seeds: 0/3"
     ]
    },
    {
     "code": "DEMO-MATH5.1",
     "subject": "Mathematics",
     "topic": "Fractions",
     "description": "Represents, compares and adds fractions with like denominators.",
     "mastery": 0.3,
     "evidence": "3 of 10 marks",
     "sources": [
      "M
...
```

## 10. AI Class tutor answer (Gyan SLM) with citations

```json
{
 "answer": "To compare the fractions 1/3 and 1/5, we need to look at their denominators. They are equal.\n\nSince they have the same denominator, we need to check if the numerators are equal. In this case, they are not. The numerator of 1/3 is 1 and the numerator of 1/5 is also 1.\n\nSo, we compare the fractions by looking at how many parts the whole is divided into. Both 1/3 and 1/5 divide the whole into equal parts.\n\nNow, let's think about it like this: if you have a pizza that is cut into 3 equal pieces and another pizza that is cut into 5 equal pieces, which one would you rather have more of? It's not because the pieces are bigger or smaller, but because there are fewer pieces in the first pizza.\n\nTherefore, 1/3 is greater than 1/5.",
 "verified": true,
 "citations": [
  {
   "chunk_id": 5,
   "text": "Demo Primer: Mathematics Class 5, Chapter 2: Fractions, p. 4",
   "document": "Demo Primer: Mathematics Class 5",
   "chapter": "Chapter 2: Fractions",
   "page": 4,
   "publisher": "DEMO (not SCERT)",
   "curriculum_version": "DEMO-2026",
   "is_demo": true,
   "ref": "S1"
  },
  {
   "chunk_id": 4,
   "text": "Demo Primer: Mathematics Class 5, Chapter 2: Fractions, p. 3",
   "document": "Demo Primer: Mathematics Class 5",
   "chapter": "Chapter 2: Fractions",
   "page": 3,
   "publisher": "DEMO (not SCERT)",
   "curriculum_version": "DEMO-2026",
   "is_demo": true,
   "ref": "S2"
  }
 ],
 "provider": "ollama:llama3.2:3b"
}
```

## 11. Hindi tutor answer

```json
{
 "answer": "भिन्न में अंश बताता है कि पूरी वस्तु को कितने बराबर भागों में बाँटा गया है। [S1] [S3]\n\nउदाहरण: एक रोटी को 4 बराबर टुकड़ों में काटा गया। मीना ने 3 टुकड़े खाए, तो उसने रोटी का 3/4 भाग खाया।",
 "verified": true,
 "citations": [
  {
   "chunk_id": 9,
   "text": "डेमो पुस्तिका: गणित कक्षा 5, अध्याय 2: भिन्न, p. 1",
   "document": "डेमो पुस्तिका: गणित कक्षा 5",
   "chapter": "अध्याय 2: भिन्न",
   "page": 1,
   "publisher": "DEMO (not SCERT)",
   "curriculum_version": "DEMO-2026",
   "is_demo": true,
   "ref": "S1"
  },
  {
   "chunk_id": 4,
   "text": "Demo Primer: Mathematics Class 5, Chapter 2: Fractions, p. 3",
   "document": "Demo Primer: Mathematics Class 5",
   "chapter": "Chapter 2: Fractions",
   "page": 3,
   "publisher": "DEMO (not SCERT)",
   "curriculum_version": "DEMO-2026",
   "is_demo": true,
   "ref": "S3"
  }
 ]
}
```

## 12. Off-syllabus question handled honestly

```json
{
 "answer": "I could not verify an answer to this from the approved textbooks for your class. Please ask your teacher, or try asking about a topic from your lessons.",
 "verified": false,
 "citations": []
}
```

## 13. Teacher Saathi grounded Q&A

```json
{
 "answer": "To explain why 1/3 is bigger than 1/5, you can say that when the numerators are equal, the fraction with the smaller denominator is bigger. This means that if we have two fractions with the same numerator (in this case, 1), the one with the smaller denominator (3) will be larger because it represents a smaller part of the whole compared to the fraction with the larger denominator (5).",
 "verified": true,
 "citations": [
  {
   "chunk_id": 5,
   "text": "Demo Primer: Mathematics Class 5, Chapter 2: Fractions, p. 4",
   "document": "Demo Primer: Mathematics Class 5",
   "chapter": "Chapter 2: Fractions",
   "page": 4,
   "publisher": "DEMO (not SCERT)",
   "curriculum_version": "DEMO-2026",
   "is_demo": true,
   "ref": "S1"
  },
  {
   "chunk_id": 4,
   "text": "Demo Primer: Mathematics Class 5, Chapter 2: Fractions, p. 3",
   "document": "Demo Primer: Mathematics Class 5",
   "chapter": "Chapter 2: Fractions",
   "page": 3,
   "publisher": "DEMO (not SCERT)",
   "curriculum_version": "DEMO-2026",
   "is_demo": true,
   "ref": "S4"
  }
 ],
 "model": "llama3.2:3b",
 "latency_ms": 3099
}
```

## 14. Command Centre - planned / taught / learned (computed from records)

```json
{
 "total": {
  "planned_due": 378,
  "taught": 207,
  "assessed": 207,
  "learned": 95,
  "taught_rate": 0.5476,
  "learned_rate": 0.4589,
  "basis": "378 outcomes scheduled up to 2026-10-14 in 54 class-subjects"
 },
 "rows": [
  {
   "id": 3,
   "name": "Demo District East",
   "planned_due": 112,
   "taught": 59,
   "assessed": 59,
   "learned": 31,
   "taught_rate": 0.5268,
   "learned_rate": 0.5254,
   "basis": "112 outcomes scheduled up to 2026-10-14 in 16 class-subjects"
  },
  {
   "id": 1,
   "name": "Demo District North",
   "planned_due": 110,
   "taught": 71,
   "assessed": 71,
   "learned": 40,
   "taught_rate": 0.6455,
   "learned_rate": 0.5634,
   "basis": "110 outcomes scheduled up to 2026-10-14 in 16 class-subjects"
  }
 ]
}
```
