import re

file_path = r'c:\Users\eskarsten\OneDrive - KONGSBERG\Documents\VIBE Projects\MailCleaner\execution\templates\dashboard.html'

def analyze_structure():
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    stack = [] # Stores (line_num, tag_info)
    
    # We want to track 'main' and 'settings-view' specifically
    main_open_line = -1
    settings_view_open_line = -1
    
    for i, line in enumerate(lines):
        line_num = i + 1
        content = line.strip()
        
        # Simple regex for opening divs (naive but likely sufficient for this template)
        # Matches <div ...> or <div>
        # Ignores comments (naive check)
        if '<!--' in content: 
            # Strip comments roughly
            content = re.sub(r'<!--.*?-->', '', content)
        
        # Find all divs in line
        # This is tricky if multiple tags on one line.
        # Let's assume one major tag per line or standard formatting.
        
        # Check for opening <main>
        if '<main' in content:
            stack.append((line_num, 'main'))
            print(f"Line {line_num}: <main> OPEN")
            main_open_line = line_num

        # Check for opening <div ...>
        # We need to handle <div id="x"> and </div> sequence
        # Find all tags in order
        tags = re.findall(r'(</?div|<!--|-->|</?main)', line)
        
        for tag in tags:
            if tag.startswith('<!--'):
                pass
            elif tag.startswith('-->'):
                pass
            elif tag.startswith('<div'):
                # Check id/class in the line for context (imprecise but helpful)
                info = 'div'
                if 'id="' in line:
                    match = re.search(r'id="([^"]+)"', line)
                    if match: info += f"#{match.group(1)}"
                elif 'class="' in line:
                    match = re.search(r'class="([^"]+)"', line)
                    if match: info += f".{match.group(1)}"
                
                stack.append((line_num, info))
                # print(f"Line {line_num}: {info} OPEN (Depth: {len(stack)})")
                
                if 'settings-view' in info:
                    print(f"Line {line_num}: #settings-view OPEN")
                    settings_view_open_line = line_num

            elif tag == '</div>':
                if not stack:
                    print(f"Line {line_num}: ERROR - Extra </div> found!")
                    continue
                    
                opener = stack.pop()
                # print(f"Line {line_num}: </div> CLOSES {opener[1]} (From Line {opener[0]})")
                
                if 'settings-view' in opener[1]:
                    print(f"Line {line_num}: #settings-view CLOSED")
                
                if 'main' in opener[1]: # Should not happen unless main is div? No main is main tag.
                    pass # handled by </main>
            
            elif tag == '</main>':
                if stack and stack[-1][1] == 'main':
                    stack.pop()
                    print(f"Line {line_num}: <main> CLOSED CORRECTLY")
                else:
                    print(f"Line {line_num}: </main> FOUND but stack top is {stack[-1] if stack else 'EMPTY'}")
                    if stack:
                         # Traverse up to find main?
                         pass

        # Stop if we reach subscriptions view
        if 'id="subscriptions-view"' in line:
            print(f"Line {line_num}: Reached 'subscriptions-view'")
            print(f"Current Stack (Depth {len(stack)}): {[x[1] for x in stack]}")
            # Check if main is in stack
            has_main = any('main' in x[1] for x in stack)
            if not has_main:
                print("CRITICAL: 'main' is NOT in stack! It was closed earlier.")
            break

if __name__ == "__main__":
    analyze_structure()
