"""Prompt for a fictional presenter still.

Flux 2 Klein text-to-image draws this prompt. The graph has no LoRA.
"""

ROLES = {
    "news": "news anchor",
    "podcast": "podcast host",
    "interview": "interviewer",
    "documentary": "documentary presenter",
    "late": "late-night host",
}

PEOPLE = {
    "woman": "woman",
    "man": "man",
}

def presenter_age(age) -> int:
    text = str("" if age is None else age).strip()
    if not text.isdigit():
        raise ValueError("Pick an age from 18 to 90.")
    years = int(text)
    if years < 18 or years > 90:
        raise ValueError("Pick an age from 18 to 90.")
    return years

WOMEN_CLOTHES = {
    "suit": "a tailored dark suit",
    "blouse": "a silk blouse under a dark jacket",
    "knit": "a fine knit over a collared shirt",
    "dress": "a simple dark dress",
    "shirt": "a crisp shirt",
    "coat": "a long coat over a dark top",
    "blazer": "a fitted blazer",
    "turtleneck": "a fine turtleneck",
}

MEN_CLOTHES = {
    "suit": "a tailored dark suit",
    "shirt": "a crisp open-collar shirt",
    "knit": "a knit layer over a collared shirt",
    "jacket": "a casual blazer",
    "coat": "a wool overcoat",
    "polo": "a dark polo shirt",
    "rollneck": "a dark rollneck",
    "vest": "a waistcoat over a shirt",
}

HAIR = {
    "black": "black",
    "dark-brown": "dark brown",
    "light-brown": "light brown",
    "blonde": "blonde",
    "auburn": "auburn",
    "grey": "grey",
}

WOMEN_STYLES = {
    "short": "short and neat",
    "bob": "in a chin-length bob",
    "waves": "in shoulder-length waves",
    "long": "long and straight",
    "curls": "in loose curls",
    "tied": "tied back",
    "bun": "in a low bun",
    "fringe": "with a soft fringe",
}

MEN_STYLES = {
    "short": "short and neat",
    "crop": "in a textured crop",
    "fade": "with a short fade",
    "side": "with a side part",
    "quiff": "in a quiff",
    "curls": "in short curls",
    "tied": "pulled back",
    "buzz": "cropped close",
}

EYES = {
    "brown": "brown",
    "blue": "blue",
    "green": "green",
    "hazel": "hazel",
    "grey": "grey",
}

GLASSES = {
    "none": "",
    "glasses": "Thin metal glasses sit on the face.",
}

FACIAL = {
    "none": "",
    "stubble": "light stubble",
    "beard": "a short beard",
}


def presenter_prompt(role, person, wardrobe, hair, style, eyes, glasses, facial, age, scene="plain") -> str:
    clothes = MEN_CLOTHES if person == "man" else WOMEN_CLOTHES
    styles = MEN_STYLES if person == "man" else WOMEN_STYLES
    chosen = {
        "role": (role, ROLES),
        "person": (person, PEOPLE),
        "wardrobe": (wardrobe, clothes),
        "hair": (hair, HAIR),
        "style": (style, styles),
        "eyes": (eyes, EYES),
        "glasses": (glasses, GLASSES),
        "facial": (facial, FACIAL),
    }
    if any(value not in options for value, options in chosen.values()):
        raise ValueError("Pick the presenter look from the lists.")
    years = presenter_age(age)
    pronoun = "She" if person == "woman" else "He"
    face = ""
    if person == "man" and FACIAL[facial]:
        face = f" {pronoun} has {FACIAL[facial]}."
    specs = f" {GLASSES[glasses]}" if GLASSES[glasses] else ""
    if scene == "both":
        place = (
            "The first reference image is the person's face. "
            "The second reference image is the room. Keep that face and that room."
        )
    elif scene == "room":
        place = "The reference image is the room. Keep that room behind the presenter."
    else:
        place = "Even studio lighting, sharp focus, plain background."
    return (
        f"A photorealistic medium close-up of a {PEOPLE[person]} {ROLES[role]} aged {years}, "
        f"seated at a broadcast desk, facing the camera. "
        f"{pronoun} has {HAIR[hair]} hair worn {styles[style]}, and {EYES[eyes]} eyes."
        f"{face}{specs} {pronoun} wears {clothes[wardrobe]}. "
        "Calm expression, mouth slightly open as if about to speak. "
        "Both hands rest on the desk. The person remains seated. "
        f"{place} No text, no logo, no watermark."
    )
