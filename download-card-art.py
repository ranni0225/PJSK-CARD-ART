# encoding: UTF-8


import asyncio
import datetime
import httpx
import json
import logging
import sys

from pathlib import Path

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


def LoadJson(filePath: Path) -> dict:
    try:
        return json.load(filePath.open("r", encoding="utf-8"))
    except Exception as e:
        logging.warning(f"Failed to load json: {e}", exc_info=True)
        return {}


def SaveJson(filePath: Path, data: dict) -> bool:
    try:
        filePath.parent.mkdir(parents=True, exist_ok=True)

        with filePath.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4, sort_keys=True)
            return True
    except Exception as e:
        logging.error(f"Failed to save json: {e}", exc_info=True)
        return False


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

manifestFile = Path("manifest.json")
manifest = LoadJson(manifestFile)

# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====
# CONSTANTS
# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

CARD_DATA_URL = "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/refs/heads/main/cards.json"
GAME_CHARACTER_DATA_URL = "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/refs/heads/main/gameCharacters.json"

CARD_ART_URL_PREFIX = "https://storage.sekai.best/sekai-jp-assets/character/member/"
CARD_ART_STAGE1_URL_SUFFIX = "/card_normal.png"
CARD_ART_STAGE2_URL_SUFFIX = "/card_after_training.png"

JST_TIMEZONE = datetime.timezone(datetime.timedelta(hours=9))


# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====
# DOWNLOADER LOGIC
# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

async def main():
    logging.info("Creating required directories...")

    requiredDirectories = [
        CARD_ART_DIRECTORY
    ]
    for requiredDirectory in requiredDirectories:
        requiredDirectory.mkdir(parents=True, exist_ok=True)

    limits = httpx.Limits(max_connections=WORKER_COUNT, max_keepalive_connections=WORKER_COUNT)
    transport = httpx.AsyncHTTPTransport(retries=RETRY_COUNT)

    async with httpx.AsyncClient(limits=limits, transport=transport, timeout=DEFAULT_TIMEOUT) as client:
        logging.info("Fetching card data...")

        try:
            response = await client.get(CARD_DATA_URL)
            response.raise_for_status()
            cards = response.json()
        except Exception as e:
            logging.error(f"Failed to fetch card data: {e}", exc_info=True)
            sys.exit(-1)

        logging.info("Fetching game character data...")

        try:
            response = await client.get(GAME_CHARACTER_DATA_URL)
            response.raise_for_status()
            gameCharacters = response.json()
        except Exception as e:
            logging.error(f"Failed to fetch game character data: {e}", exc_info=True)
            sys.exit(-1)

        characterNames = {
            gameCharacter["id"]: f"{gameCharacter.get('firstName', '')} {gameCharacter.get('givenName', '')}".strip() for gameCharacter in gameCharacters
        }

        logging.info("Downloading card art...")

        async def DownloadCardArt(url: str, filePath: Path) -> bool:
            filePath.parent.mkdir(parents=True, exist_ok=True)

            if manifest.get(filePath.name):
                return True

            try:
                async with client.stream("GET", url) as response:
                    if response.status_code == 404:
                        return True
                    response.raise_for_status()

                    logging.info(f"Downloading \"{filePath.name}\"")

                    with filePath.open("wb") as file:
                        async for chunk in response.aiter_bytes(chunk_size=4096):
                            file.write(chunk)

                manifest[filePath.name] = url

                return True
            except Exception as e:
                logging.error(f"Failed to download card art \"{url}\" to \"{filePath}\": {e}", exc_info=True)

                if filePath.exists():
                    filePath.unlink()

                return False

        async def ProcessSingleCard(card: dict):
            cardId = card.get("id", "")
            cardAssetId = card.get("assetbundleName", "")

            cardReleaseTime = datetime.datetime.fromtimestamp(card.get("releaseAt", 0) / 1000, tz=JST_TIMEZONE).strftime("%Y%m%d")
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

            await DownloadCardArt(f"{CARD_ART_URL_PREFIX}{cardAssetId}{CARD_ART_STAGE1_URL_SUFFIX}", CARD_ART_DIRECTORY / cardReleaseYear / f"{cardFileBaseName}.png")
            if cardIsTrainable:
                await DownloadCardArt(f"{CARD_ART_URL_PREFIX}{cardAssetId}{CARD_ART_STAGE2_URL_SUFFIX}", CARD_ART_DIRECTORY / cardReleaseYear / f"{cardFileBaseName} [+].png")

        semaphore = asyncio.Semaphore(WORKER_COUNT)

        async def _ProcessSingleCard(card: dict):
            async with semaphore:
                try:
                    await ProcessSingleCard(card)
                except Exception as e:
                    logging.error(f"Exception occurred during processing card #{card.get('id')}: {e}", exc_info=True)

        tasks = [_ProcessSingleCard(card) for card in cards]
        await asyncio.gather(*tasks)

    SaveJson(manifestFile, manifest)


if __name__ == "__main__":
    asyncio.run(main())
