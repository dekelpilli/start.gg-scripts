import json
import logging

import requests
from mergedeep import merge, Strategy
import os
import sys
from collections import Counter

DATA_DIR = os.path.dirname(os.path.realpath(sys.argv[0])) + os.sep + "data" + os.sep


class TooManyRequestsError(Exception):
    # Means we're submitting too many requests
    pass


class ResponseError(Exception):
    # Unknown other error
    pass


class RequestError(Exception):
    # Bad request (normally means your key is wrong)
    pass


class ServerError(Exception):
    # Server error, not my fault
    pass


class NoIdeaError(Exception):
    # If you get this, please send this to me so I can figure it out lol
    pass


# appropriated from Etossed
def run_query(query, variables, header):
    json_request = {'query': query, 'variables': variables}
    try:
        request = requests.post(url='https://api.start.gg/gql/alpha', json=json_request, headers=header)
        if request.status_code == 400:
            raise RequestError
        elif request.status_code == 429:
            raise TooManyRequestsError
        elif 400 <= request.status_code < 500:
            raise ResponseError
        elif 500 <= request.status_code < 600:
            raise ServerError
        elif 300 <= request.status_code < 400:
            raise NoIdeaError

        response = request.json()
        return response

    except RequestError:
        print("Error 400: Bad request (probably means your key is wrong)")
        return 400

    except TooManyRequestsError:
        print("Error 429: Sending too many requests right now")
        return 429

    except ResponseError:
        print("Error {}: Unknown request error".format(request.status_code))
        return 404

    except ServerError:
        print("Error {}: Unknown server error".format(request.status_code))
        return 500

    except NoIdeaError:
        print("Error {}: I literally have no idea how you got this status code, please send this to me".format(
            request.status_code))
        return


ENTRANT_SELECTIONS_QUERY = """
query Chars($slug: String!) {
  event(slug: $slug) {
    videogame {
        characters {
            id
            name
        }
    }
    sets(perPage: 48, page: 1, sortType: RECENT) {
        nodes {
            games {
                selections {
                    entrant {
                        name
                    }
                    selectionValue
                }
            }
        }
    }
  }
}  
"""

SUBSEQUENT_PAGE_QUERY = """
query Chars($slug: String!, $page: Int) {
  event(slug: $slug) {
    sets(perPage: 49, page: $page, sortType: RECENT) {
        nodes {
            games {
                selections {
                    entrant {
                        name
                    }
                    selectionValue
                }
            }
        }
    }
  }
}
"""


def query_data(slug, headers):
    # sizes
    # sets = 6 + 20*numberOfSets
    # videogame = 29
    variables = {"slug": slug}
    main_response = run_query(ENTRANT_SELECTIONS_QUERY, variables, headers)
    if main_response['extensions']['queryComplexity'] > 980:
        page = 2
        while True:
            variables['page'] = page
            response = run_query(SUBSEQUENT_PAGE_QUERY, variables, headers)
            main_response['data']['games'] += response['data']['games']
            if response['extensions']['queryComplexity'] < 980:
                break
            page += 1
    return main_response['data']


def derive_name(entrant_name):
    sections = entrant_name.split("|")
    if len(sections) == 1:
        return entrant_name
    else:
        return sections[1].strip()


def log_missing_data(data_list, name, expected_keys):
    non_none_data = list(filter(lambda x: x is not None, data_list))
    diff = len(data_list) - len(non_none_data)
    if diff:
        logging.warning("Received %s '%s', and %s were missing data.", len(data_list), name, diff)

    for key in expected_keys:
        key_nones = len(list(filter(lambda x: x.get(key) is None, non_none_data)))
        if key_nones:
            logging.warning("Of %s '%s' with data, %s were missing data for the '%s' key.",
                            len(non_none_data),
                            name,
                            key_nones,
                            key)


def build_data(slug):
    headers = {"Authorization": "Bearer <your token here>"}
    response = query_data(slug, headers)
    event = response['event']
    chars = {character['id']: character['name'] for character in event['videogame']['characters']}
    node_games = [node['games'] for node in event['sets']['nodes'] if node['games'] is not None]

    log_missing_data(event['sets']['nodes'], 'sets', ['games'])

    games = [game for games in node_games
             for game in games if game is not None]

    log_missing_data(games, 'games', ['selections'])

    game_selections = [game['selections'] for game in games]

    selections = [selection for selections in game_selections if selections is not None
                  for selection in selections]

    log_missing_data(node_games, 'games', [])

    player_character_choices = [{'player': derive_name(selection['entrant']['name']),
                                 'character': chars[selection['selectionValue']]}
                                for selection in selections]
    player_char_freqs = {}
    character_counts = {char: 0 for char in sorted(chars.values())}
    for selection in player_character_choices:
        player = selection['player']
        char = selection['character']
        player_char_freqs[player] = player_char_freqs.get(player, character_counts.copy())
        player_char_freqs[player][char] = player_char_freqs[player][char] + 1

    return player_char_freqs


def create_json_frequencies(slug):
    data = build_data(slug)

    file_name = DATA_DIR + 'slugs/' + slug + '/character_frequencies.json'
    os.makedirs(os.path.dirname(file_name), exist_ok=True)

    with open(file_name, 'w+', encoding='utf-8') as slug_file:
        json.dump(data, slug_file, indent=2)

    print("\nFile '" + file_name + "'Created.")

    totals = {}
    for path, subdirs, files in os.walk(DATA_DIR + 'slugs/'):
        for name in files:
            with open(os.path.join(path, name), 'r') as current_slug_file:
                event_counts = json.load(current_slug_file)
                counters = {k: Counter(v) for k, v in event_counts.items()}
                totals = merge(totals, counters, strategy=Strategy.ADDITIVE)

    with open(DATA_DIR + 'total_character_frequencies.json', 'w+', encoding='utf-8') as totals_file:
        json.dump(totals, totals_file, indent=2)

    print("Convert me: https://www.convertcsv.com/json-to-csv.htm")


def main():
    slug = str(input("Please enter event slug: "))
    # e.g. tournament/beginner-beatdown-89-milk-edition-1/event/melee-singles
    create_json_frequencies(slug)


if __name__ == "__main__":
    main()
