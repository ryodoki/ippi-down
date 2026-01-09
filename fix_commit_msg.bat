@echo off
set FILTER_BRANCH_SQUELCH_WARNING=1
git filter-branch -f --msg-filter "if test \"$GIT_COMMIT\" = \"5563596980ebb2f58d326a0546d5930eca9b6ba4\"; then echo docs: add code review document; elif test \"$GIT_COMMIT\" = \"2bb1124b9b793d15595bd7bf565b7168b611bf5f\"; then echo feat: improve core functionality based on code review; else cat; fi" --tag-name-filter cat -- --branches --tags
