import sys
def parse_numbers(text):
    return [int(part) for part in text.split(',') if part.strip()]
if __name__ == '__main__':
    print(sum(parse_numbers(sys.argv[1])))
