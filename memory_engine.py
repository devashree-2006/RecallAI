import random
import re
import string

WORD_BANK = {
    1: ["apple", "river", "chair", "cloud", "pencil", "garden"],
    2: ["lantern", "forest", "bottle", "silver", "window", "basket", "planet"],
    3: ["compass", "harvest", "blanket", "diamond", "journey", "library", "thunder", "picture"],
    4: ["calendar", "mountain", "umbrella", "butterfly", "hospital", "triangle", "keyboard", "sunflower", "football"],
    5: ["adventure", "waterfall", "telescope", "chocolate", "electricity", "newspaper", "pineapple", "notebook", "airplane", "rainbow"]
}

STORY_BANK = {
    1: [{
        "story": "Maya visited a park on Sunday. She saw three ducks near a pond and ate a red apple on a bench.",
        "questions": [
            {"question": "Where did Maya go?", "answer": ["park"]},
            {"question": "How many ducks did she see?", "answer": ["three", "3"]},
            {"question": "What fruit did she eat?", "answer": ["apple"]}
        ]
    }],
    2: [{
        "story": "On Monday morning, Ravi took a blue bag to the library. He borrowed two books about space and returned home by bus.",
        "questions": [
            {"question": "What colour was the bag?", "answer": ["blue"]},
            {"question": "How many books did Ravi borrow?", "answer": ["two", "2"]},
            {"question": "How did he return home?", "answer": ["bus", "by bus"]}
        ]
    }],
    3: [{
        "story": "Neha travelled to Mysuru with her cousin in June. They visited a palace, took twelve photographs, and had lunch at a small restaurant.",
        "questions": [
            {"question": "Which city did Neha visit?", "answer": ["mysuru", "mysore"]},
            {"question": "Who travelled with her?", "answer": ["cousin"]},
            {"question": "How many photographs did they take?", "answer": ["twelve", "12"]},
            {"question": "Where did they have lunch?", "answer": ["restaurant"]}
        ]
    }],
    4: [{
        "story": "During a school science exhibition on Friday, Arjun displayed a model of a solar-powered house. His team won second place, and their teacher gave them a certificate.",
        "questions": [
            {"question": "What did Arjun display?", "answer": ["solar-powered house", "solar powered house", "house"]},
            {"question": "When was the exhibition?", "answer": ["friday"]},
            {"question": "Which place did the team win?", "answer": ["second", "second place"]},
            {"question": "What did the teacher give them?", "answer": ["certificate"]}
        ]
    }],
    5: [{
        "story": "A wildlife photographer named Sara reached a coastal village before sunrise. She recorded a rare sea turtle nesting near a lighthouse, noted the time as 5:20 AM, and sent the observation to a conservation centre.",
        "questions": [
            {"question": "What was Sara's profession?", "answer": ["photographer", "wildlife photographer"]},
            {"question": "Where was the turtle nesting?", "answer": ["near a lighthouse", "lighthouse", "coast", "coastal village"]},
            {"question": "What time did she record?", "answer": ["5:20 am", "5:20", "5 20", "five twenty"]},
            {"question": "Where did she send the observation?", "answer": ["conservation centre", "conservation center"]}
        ]
    }]
}


def generate_word_challenge(difficulty):
    count = min(difficulty + 3, len(WORD_BANK[difficulty]))
    items = random.sample(WORD_BANK[difficulty], count)
    return {
        "type": "word",
        "difficulty": difficulty,
        "display_time": max(5, 12 - difficulty),
        "items": items
    }


def generate_number_challenge(difficulty):
    length = difficulty + 3
    numbers = [str(random.randint(0, 9)) for _ in range(length)]
    return {
        "type": "number",
        "difficulty": difficulty,
        "display_time": max(5, 12 - difficulty),
        "items": numbers
    }


def generate_story_challenge(difficulty):
    item = random.choice(STORY_BANK[difficulty])
    return {
        "type": "story",
        "difficulty": difficulty,
        "display_time": max(8, 20 - difficulty * 2),
        "story": item["story"],
        "questions": item["questions"]
    }


def generate_challenge(challenge_type, difficulty):
    difficulty = max(1, min(5, int(difficulty)))
    if challenge_type == "word":
        return generate_word_challenge(difficulty)
    if challenge_type == "number":
        return generate_number_challenge(difficulty)
    if challenge_type == "story":
        return generate_story_challenge(difficulty)
    raise ValueError("Unknown challenge type")


def normalize_text(text):
    text = str(text).lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return " ".join(text.split())


def evaluate_word_answer(expected_words, user_answer):
    submitted = [
        normalize_text(word)
        for word in re.split(r"[,;\s]+", str(user_answer))
        if normalize_text(word)
    ]
    expected = [normalize_text(word) for word in expected_words]
    correct = list(dict.fromkeys(word for word in submitted if word in expected))
    missed = [word for word in expected if word not in submitted]
    extra = [word for word in submitted if word not in expected]
    score = round(len(correct) / max(1, len(expected)) * 100, 2)
    return {
        "score": score,
        "correct_count": len(correct),
        "total_count": len(expected),
        "correct": correct,
        "missed": missed,
        "extra": extra
    }


def evaluate_number_answer(expected_numbers, user_answer):
    submitted = re.findall(r"\d+", str(user_answer))
    expected = [str(number) for number in expected_numbers]
    correct = sum(
        1 for index, number in enumerate(expected)
        if index < len(submitted) and submitted[index] == number
    )
    score = round(correct / max(1, len(expected)) * 100, 2)
    return {
        "score": score,
        "correct_count": correct,
        "total_count": len(expected),
        "expected": expected,
        "submitted": submitted
    }


def evaluate_story_answer(questions, answers):
    correct = 0
    details = []

    for index, question in enumerate(questions):
        answer = normalize_text(answers[index]) if index < len(answers) else ""
        accepted = [normalize_text(value) for value in question["answer"]]
        matched = bool(answer) and any(
            expected in answer or answer in expected
            for expected in accepted
        )
        if matched:
            correct += 1
        details.append({
            "question": question["question"],
            "correct": matched
        })

    score = round(correct / max(1, len(questions)) * 100, 2)
    return {
        "score": score,
        "correct_count": correct,
        "total_count": len(questions),
        "details": details
    }


def calculate_new_skill(old_skill, current_score, old_attempts=0):
    if old_attempts <= 0:
        return round(current_score, 2)

    average = (
        old_skill * old_attempts + current_score
    ) / (old_attempts + 1)

    return round(average, 2)



def difficulty_from_skill(skill_score):
    if skill_score < 30:
        return 1
    if skill_score < 45:
        return 2
    if skill_score < 60:
        return 3
    if skill_score < 80:
        return 4
    return 5


def choose_challenge_type(skills):
    types = ["word", "number", "story"]
    if not skills:
        return random.choice(types)

    scores = {skill["challenge_type"]: skill["skill_score"] for skill in skills}
    weakest = min(types, key=lambda kind: scores.get(kind, 50))

    if random.random() < 0.65:
        return weakest
    return random.choice(types)


def calculate_overall_score(skills):
    if not skills:
        return 0
    return round(sum(skill["skill_score"] for skill in skills) / len(skills), 2)
