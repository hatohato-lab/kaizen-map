"""レシピ工房アプリ本体（架空の見本）。"""
import utils
import pricing
import settings

def main():
    print(utils.normalize("Tomato Soup"), pricing.price(3), settings.API_TOKEN[:2])
