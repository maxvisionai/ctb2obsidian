import urllib.request


def fetch_ip_info():
    url = "https://ipinfo.io/json"
    with urllib.request.urlopen(url) as response:
        data = response.read().decode()
    print(data)


if __name__ == "__main__":
    fetch_ip_info()
