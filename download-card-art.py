# encoding: UTF-8


import datetime
import logging
import sys

import requests

from concurrent.futures import as_completed, ThreadPoolExecutor
from pathlib import Path

from requests.adapters import HTTPAdapter

# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====
# GLOBAL CONFIGURATION
# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

WORKER_COUNT = 8
RETRY_COUNT = 5
DEFAULT_TIMEOUT = 15

CARD_ART_DIRECTORY = Path("card-art")

logging.addLevelName(logging.DEBUG, "d")
logging.addLevelName(logging.INFO, "i")
logging.addLevelName(logging.WARNING, "w")
logging.addLevelName(logging.ERROR, "e")
logging.addLevelName(logging.CRITICAL, "c")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)

session = requests.Session()
session.mount("http://", HTTPAdapter(pool_connections=WORKER_COUNT, pool_maxsize=WORKER_COUNT, max_retries=RETRY_COUNT))
session.mount("https://", HTTPAdapter(pool_connections=WORKER_COUNT, pool_maxsize=WORKER_COUNT, max_retries=RETRY_COUNT))

# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====
# CONSTANTS
# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

CARD_DATA_URL = "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/refs/heads/main/cards.json"
GAME_CHARACTER_DATA_URL = "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/refs/heads/main/gameCharacters.json"

CARD_ART_URL_PREFIX = "https://storage.sekai.best/sekai-jp-assets/character/member/"
CARD_ART_STAGE1_URL_SUFFIX = "/card_normal.png"
CARD_ART_STAGE2_URL_SUFFIX = "/card_after_training.png"

# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====
# HELPER FUNCTIONS
# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

TRANSLATE_MAP = str.maketrans({
    "*": "＊",
    "/": "／",
    ":": "：",
    "<": "＜",
    ">": "＞",
    "?": "？",
    "\"": "＂",
    "\\": "＼",
    "|": "｜"
})


def ReplaceInvalidCharacters(s: str) -> str:
    return s.translate(TRANSLATE_MAP)


# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====
# DOWNLOADER LOGIC
# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

logging.info("Creating required directories...")

requiredDirectories = [
    CARD_ART_DIRECTORY
]
for requiredDirectory in requiredDirectories:
    requiredDirectory.mkdir(parents=True, exist_ok=True)

logging.info("Fetching card data...")

try:
    response = session.get(CARD_DATA_URL, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    cards = response.json()
except Exception as e:
    logging.error(f"Failed to fetch card data: {e}", exc_info=True)
    sys.exit(-1)

logging.info("Fetching game character data...")

try:
    response = session.get(GAME_CHARACTER_DATA_URL, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    gameCharacters = response.json()
except Exception as e:
    logging.error(f"Failed to fetch game character data: {e}", exc_info=True)
    sys.exit(-1)

characterNames = {
    gameCharacter["id"]: f"{gameCharacter.get('firstName', '')} {gameCharacter.get('givenName', '')}".strip() for gameCharacter in gameCharacters
}

logging.info("Downloading card art...")


def DownloadCardArt(url: str, filePath: Path) -> bool:
    filePath.parent.mkdir(parents=True, exist_ok=True)

    if filePath.exists() and filePath.stat().st_size > 0:
        return True

    try:
        response = session.get(url, stream=True, timeout=DEFAULT_TIMEOUT)

        if response.status_code == 404:
            return True
        response.raise_for_status()

        logging.info(f"Downloading \"{filePath.name}\"")

        with filePath.open("wb") as file:
            for chunk in response.iter_content(chunk_size=4096):
                file.write(chunk)

        return True
    except Exception as e:
        logging.error(f"Failed to download card art \"{url}\" to \"{filePath}\": {e}", exc_info=True)

        if filePath.exists():
            filePath.unlink()

        return False


def ProcessSingleCard(card: dict):
    cardId = card.get("id", "")
    cardAssetId = card.get("assetbundleName", "")

    cardReleaseTime = datetime.datetime.fromtimestamp(card.get("releaseAt", 0) / 1000).strftime("%Y%m%d")
    cardRarity = card.get("cardRarityType", "rarity_none").split('_')[-1].lower()
    cardName = card.get("prefix", "")
    cardCharacterId = card.get("characterId", "")

    cardCharacterName = characterNames.get(cardCharacterId, "")

    cardIsTrainable = cardRarity in [
        "3",
        "4",
    ]
    cardReleaseYear = cardReleaseTime[:4]

    logging.info(f"Processing card #{cardId}({cardAssetId}):\t [{cardReleaseTime}] {cardCharacterName} - {cardName}")

    cardFileBaseName = ReplaceInvalidCharacters(f"[{cardReleaseTime}][{cardCharacterName}][{cardRarity}] {cardName}")

    DownloadCardArt(f"{CARD_ART_URL_PREFIX}{cardAssetId}{CARD_ART_STAGE1_URL_SUFFIX}", CARD_ART_DIRECTORY / cardReleaseYear / f"{cardFileBaseName}.png")
    if cardIsTrainable:
        DownloadCardArt(f"{CARD_ART_URL_PREFIX}{cardAssetId}{CARD_ART_STAGE2_URL_SUFFIX}", CARD_ART_DIRECTORY / cardReleaseYear / f"{cardFileBaseName} [+].png")


with ThreadPoolExecutor(max_workers=WORKER_COUNT) as executor:
    futureToCards = {executor.submit(ProcessSingleCard, card): card for card in cards}

    for future in as_completed(futureToCards):
        try:
            future.result()
        except Exception as e:
            logging.error(f"Exception occurred during processing card #{futureToCards[future]['id']}: {e}", exc_info=True)
