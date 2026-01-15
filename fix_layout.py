import os

file_path = r'c:\Users\eskarsten\OneDrive - KONGSBERG\Documents\VIBE Projects\MailCleaner\execution\templates\dashboard.html'

def fix_dashboard():
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Find the start of the bad block (around line 340)
    start_index = -1
    end_index = -1
    
    # We look for the sequence ending in the 0-indented div before Subscriptions
    # The file currently has 0-indented </div> at line 340, empty 341, <!-- Subscriptions View --> 342
    for i in range(len(lines)):
        if '<!-- Subscriptions View -->' in lines[i]:
            # The bad </div> should be somewhere before this
            # In previous view it was at i-2
            start_index = i - 2
            # Verify it is a div
            if '</div>' in lines[start_index]:
                print(f"Found start of block at line {start_index} (content: {lines[start_index].strip()})")
            else:
                print(f"Warning: Line {start_index} is not '</div>', it is: {lines[start_index]}")
            break

    # Find the end (</main>)
    for i in range(len(lines)-1, -1, -1):
        if '</main>' in lines[i]:
            end_index = i
            break
            
    if start_index != -1 and end_index != -1:
        print(f"Replacing block from line {start_index} to {end_index}")
        
        # Replacement content with correct indentation (8 spaces for views, 4 for main closing)
        replacement = r"""        </div>

        <!-- Subscriptions View -->
        <div id="subscriptions-view" class="view">
            <div class="section-header">
                <h2>Newsletter Audit</h2>
            </div>
            <div class="card">
                <div class="card-content">
                    <div style="overflow-x: auto;">
                        <table class="table" style="width:100%">
                            <thead>
                                <tr>
                                    <th>Sender</th>
                                    <th>Volume</th>
                                    <th>Last Email</th>
                                    <th>Action</th>
                                </tr>
                            </thead>
                            <tbody id="subscription-list"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <!-- AI Cleanup View -->
        <div id="cleanup-view" class="view">
            <div class="section-header">
                <h2>AI Cleanup Suggestions</h2>
                <button class="btn btn-primary" onclick="loadCleanupSuggestions()">
                    <i class="ri-refresh-line"></i> Refresh Suggestions
                </button>
            </div>
            <div id="cleanup-intro" class="glass-panel" style="margin-bottom: 2rem; padding: 2rem; text-align: center;">
                <i class="ri-robot-line" style="font-size: 3rem; color: var(--primary-color);"></i>
                <h3>Let AI Clean Your Inbox</h3>
                <p>The AI will scan your "Uncertain" and promotional emails to identify junk.</p>
                <button class="btn btn-primary btn-lg" style="margin-top: 1rem;" onclick="loadCleanupSuggestions()">
                    Start Scan
                </button>
            </div>
            <div id="cleanup-loading" style="display:none; text-align:center; padding:4rem;">
                <i class="ri-loader-4-line spin" style="font-size:3rem; color: var(--primary-color);"></i>
                <p style="margin-top: 1rem;">Analyzing emails with Local LLM...</p>
            </div>
            <div id="cleanup-results" class="email-list"></div>
        </div>
    </main>
"""
        # Construct new content
        # lines[:start_index] includes lines 0 to start_index-1
        # We want to replace starting at start_index
        new_content = lines[:start_index]
        new_content.append(replacement)
        # We want to keep lines AFTER end_index.
        # end_index is the line with </main>. We are replacing it.
        new_content.extend(lines[end_index+1:])
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(new_content)
        print("Successfully updated dashboard.html")
    else:
        print("Could not locate the block to replace in dashboard.html")

if __name__ == "__main__":
    fix_dashboard()
