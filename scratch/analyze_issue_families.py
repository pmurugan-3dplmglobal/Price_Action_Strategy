import os
import sys
import re

# Ensure UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

issues = []
curr_issue = {}

with open('ISSUE_MANAGEMENT.yaml', encoding='utf-8') as f:
    for line in f:
        line_clean = line.rstrip()
        if re.match(r'^- id:\s*(ISSUE-\d+|FEATURE-\d+)', line_clean):
            if curr_issue:
                issues.append(curr_issue)
            curr_issue = {"id": re.match(r'^- id:\s*(.+)', line_clean).group(1).strip()}
        elif curr_issue:
            m_title = re.match(r'^\s+title:\s*(.+)', line_clean)
            if m_title:
                curr_issue["title"] = m_title.group(1).strip()
            m_fam = re.match(r'^\s+family:\s*(.+)', line_clean)
            if m_fam:
                curr_issue["family"] = m_fam.group(1).strip()
            m_date = re.match(r'^\s+date_reported:\s*[\'"]?([^\'"]+)', line_clean)
            if m_date:
                curr_issue["date"] = m_date.group(1).strip()
            m_cat = re.match(r'^\s+category:\s*(.+)', line_clean)
            if m_cat:
                curr_issue["category"] = m_cat.group(1).strip()

if curr_issue:
    issues.append(curr_issue)

print(f"Total Active Issues Parsed: {len(issues)}")

families = {}
for iss in issues:
    fam = iss.get('family', 'UNKNOWN')
    families.setdefault(fam, []).append(iss)

print("\n=== ISSUES GROUPED BY FAMILY ===")
for fam, items in sorted(families.items(), key=lambda x: len(x[1]), reverse=True):
    print(f"\n📁 Family: {fam} ({len(items)} issues)")
    for item in items:
        iss_id = item.get("id")
        title = item.get("title", "")[:85]
        date = item.get("date", "")
        print(f"   • [{iss_id}] ({date}): {title}")
