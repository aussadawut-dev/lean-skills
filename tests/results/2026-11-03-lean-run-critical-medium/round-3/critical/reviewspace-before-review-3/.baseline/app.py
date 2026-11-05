import json
import sys
import vault
if __name__ == '__main__':
    request=json.loads(sys.argv[2])
    operation=request.pop('op')
    result=getattr(vault,operation)(sys.argv[1],**request)
    print(json.dumps(result))
