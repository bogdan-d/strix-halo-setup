import sys

total = 0
for line in sys.stdin.read().split('\n'):
    line = line.strip()
    if line:
        total += int(line)
print(total)
