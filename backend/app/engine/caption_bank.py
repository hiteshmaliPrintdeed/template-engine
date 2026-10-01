"""
Local caption bank: hand-written lines that cost nothing and are always there.

Used two ways:
  * offline (no Gemini key, 'generic' strategy, or Gemini failing), as the
    source that keeps every spread's caption different, and
  * online, to backfill whenever Gemini's validated lines fall short of the
    spreads they must cover -- so a short response never means a repeat.

Every line obeys the same rules as Gemini's (tests/test_unique_captions.py
checks each one): it must stay true under ANY photo it lands under, so no time
of day, light, weather, indoor/outdoor, specific place or object, specific
relationship, or mention of the medium. NEUTRAL lines go on spreads where face
detection found nobody (landscapes, animals, details), so they also never
mention smiles, laughter, friends or gathering; PEOPLE lines only go on spreads
with faces.
"""

from typing import Dict, List

GENERAL_NEUTRAL: List[str] = [
    "A moment worth keeping", "Every detail tells a story", "Where the story unfolds",
    "Worth remembering always", "Held in a single moment", "The little things matter",
    "A pause worth holding", "Simple moments, lasting memories", "Stories worth telling",
    "Something worth remembering", "Moments that stay with us", "A memory in the making",
    "Treasured for years to come", "The beauty of the ordinary", "A world of small wonders",
    "Quietly unforgettable", "Moments that matter most", "Kept close to the heart",
    "A story still unfolding", "Every moment counts", "Worth every second",
    "Memories that never fade", "Wonder in the details", "Stillness worth keeping",
    "A time to remember", "The heart of the story", "Where memories begin",
    "Always worth a second look", "Beauty in every moment", "A treasure to keep",
    "The story continues", "A feeling worth keeping", "Unforgettable in every way",
    "A moment all its own", "Details that tell the tale", "Time well spent",
    "Here and now", "A memory to hold", "Pure and simple joy",
    "The best kind of moment", "Captivating from every angle", "A scene to remember",
    "Too good to forget", "Etched in memory", "Moments like these",
    "Every piece of the story", "A story in every detail", "Remembered with warmth",
    "One more to remember", "Where wonder lives", "A place in our hearts",
    "The quiet beauty of it all", "An unforgettable sight", "Moments made to last",
    "A timeless feeling", "Endlessly worth remembering", "A sight worth keeping",
    "Simply unforgettable", "The magic of the moment", "Memories in every direction",
]

GENERAL_PEOPLE: List[str] = [
    "Smiles that say it all", "Laughter we will never forget", "Together in this moment",
    "The joy of being together", "Side by side", "Faces full of joy",
    "Shared smiles, shared stories", "Happiness looks good on us", "Joy in every smile",
    "Moments shared with loved ones", "Better together", "Hearts full of joy",
    "Laughing until it hurts", "Surrounded by good company", "Friends who feel like family",
    "The best of company", "Pure happiness, shared", "Smiling from the heart",
    "Everyone we love in one place", "Joy that brings us close", "Close to the people who matter",
    "Laughter fills every moment", "All smiles here", "The warmth of good company",
    "Moments with the ones we love", "Happiest when together", "Joy written on every face",
    "Our favorite people", "Shared laughter, lasting bonds", "Love in every smile",
]

# Per category: (neutral, people). Category names match CATEGORY_THEMES_MAP.
CATEGORY_LINES: Dict[str, Dict[str, List[str]]] = {
    "Family": {
        "neutral": ["Where our story takes root", "Roots that run deep", "A legacy of love",
                    "The heart of our story", "Growing in every season", "Traditions worth keeping",
                    "The ties that bind", "A story of belonging", "Love passed down", "Our story, our way"],
        "people": ["Family is everything", "Generations of love", "The family we cherish",
                   "Love that brings us close", "Our favorite faces", "Growing up side by side"],
    },
    "Travel": {
        "neutral": ["Wanderlust in every step", "New horizons await", "The journey is the reward",
                    "Every step an adventure", "Collecting moments, not things", "Far from the everyday",
                    "Discovering the unknown", "The world is waiting", "Adventure awaits", "Onward to the next"],
        "people": ["Exploring side by side", "Adventures shared together", "Travel buddies for life",
                   "Wandering with the best company", "Smiles from far away", "Discovering it all together"],
    },
    "Celebration": {
        "neutral": ["Let the celebration begin", "A day of pure joy", "Something to celebrate",
                    "Joy in every detail", "An occasion to remember", "Celebrating every moment",
                    "Here's to this moment", "A reason to celebrate", "Festive from start to finish",
                    "The celebration continues"],
        "people": ["Cheers to good times", "Celebrating with our favorite people", "Raising a toast together",
                   "Laughter and celebration", "Joy shared by all", "Smiles all around"],
    },
    "Everyday": {
        "neutral": ["The beauty of an ordinary day", "Little moments, big meaning", "Everyday magic",
                    "Life, simply lived", "The rhythm of our days", "Small joys matter most",
                    "Just another good day", "Ordinary made extraordinary", "The quiet everyday",
                    "Moments in between"],
        "people": ["Everyday smiles", "Life with our favorite people", "Simple days, happy faces",
                   "Laughter in the everyday", "Ordinary days, together", "The joy of simply being together"],
    },
    "Portraits": {
        "neutral": ["A portrait of a moment", "Character in every detail", "Beautifully yourself",
                    "A study in expression", "Timeless and true", "Presence captivating",
                    "Every look tells a story", "Simply striking", "Grace in stillness",
                    "True to the moment"],
        "people": ["A smile worth remembering", "Joy you can see", "Faces we love",
                   "The warmth of a smile", "Expressions of joy", "A face full of story"],
    },
    "Nature": {
        "neutral": ["Wild and wonderful", "Nature's quiet wonder", "Where the wild things are",
                    "Untamed beauty", "The earth in all its glory", "A world of wonder",
                    "Beauty found in nature", "Into the wild", "Nature at its finest",
                    "The calm of the wild"],
        "people": ["Exploring the wild together", "Nature with good company", "Wonder shared",
                   "Smiles in the wild", "Discovering nature side by side", "Wild adventures together"],
    },
    "Lifestyle": {
        "neutral": ["Living the moment", "Style in every detail", "Life well lived",
                    "The art of living", "Effortlessly us", "Moments with style",
                    "Living beautifully", "A life worth living", "Details that define us",
                    "Simply our style"],
        "people": ["Living it up together", "Good vibes, good company", "Life with the best people",
                   "Smiles and good times", "Living fully, laughing often", "Together in style"],
    },
    "Milestones": {
        "neutral": ["A milestone to remember", "Hard work, well rewarded", "Ready for the next step",
                    "A moment years in the making", "Reaching new heights", "The best is yet to come",
                    "A dream fulfilled", "Proud of every step", "A new season of pride",
                    "Looking ahead with pride"],
        "people": ["Celebrating this achievement together", "Proud smiles all around", "Cheers to the next step",
                   "Sharing this proud moment", "Joy in every achievement", "Celebrating how far we have come"],
    },
    "Activities": {
        "neutral": ["In the thick of it", "Every move counts", "Full of energy",
                    "The thrill of it all", "Action in every moment", "Game on",
                    "The spirit of play", "All in", "Energy that never stops", "Momentum in motion"],
        "people": ["Playing together", "Team spirit at its best", "Fun with the whole crew",
                   "Laughter in the action", "Energy shared by all", "Cheering each other on"],
    },
    "Memories": {
        "neutral": ["Memories we hold dear", "Looking back with love", "A trip down memory lane",
                    "Moments to hold forever", "Where memories live", "Timeless treasures",
                    "The past, beautifully kept", "Stories we will retell", "Echoes of good times",
                    "Forever in our hearts"],
        "people": ["Remembering the good times together", "Faces we will always remember", "Shared memories, shared smiles",
                   "The ones who made it special", "Laughter we will always recall", "Together in every memory"],
    },
}


def bank_lines(category: str, kind: str) -> List[str]:
    """Category lines first (most on-topic), then the general ones."""
    specific = CATEGORY_LINES.get(category, {}).get(kind, [])
    general = GENERAL_PEOPLE if kind == "people" else GENERAL_NEUTRAL
    return list(specific) + [line for line in general if line not in specific]
