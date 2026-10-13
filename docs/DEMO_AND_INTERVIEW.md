# Demo script and interview preparation

## Five-minute demo script

Before you start: activate the virtual environment, run `python -m pytest -v`
once so you know everything passes, then run `streamlit run app.py`.

**1. The problem (30 seconds)**

"Colleges award merit scholarships based on CGPA. Doing this by hand in a
spreadsheet is slow and error-prone, especially at boundaries like exactly
8.0. I built a tool that applies the rules consistently, flags bad data, and
lets an administrator search the results. It's Phase 1 of a project inspired
by an enterprise AI agent that uses Gemini and Google Sheets."

**2. The dashboard (45 seconds)**

Point at the three numbers and the chart. "Twenty students were checked. Fifteen
qualify. The chart shows five per tier." Point at the sidebar: "These are the
rules. They come from a CSV file, so changing a rule doesn't need a code change."

**3. Boundary cases (60 seconds)**

Scroll the Eligible table. "Ananya has exactly 9.00 and gets 50%. Saanvi has
8.99 and gets 25%, not 50%. Kavya has 6.99, so she is in the Not eligible tab."
Then type `8` into **Check a CGPA** and show Silver, then `7.99` and show Bronze.

**4. Search and filters (60 seconds)**

Type `sharma` in the search box: one result. Type `zzz`: show the helpful
"No students match" message. Clear it. Choose **25%** with **Exactly**: five
students. Switch to **At least**: ten students (25% and 50%).

**5. Bad data (60 seconds)**

In the sidebar choose **Sample with data errors**. "Real data is messy. This
file has a missing CGPA, the word 'eleven', 10.5, a negative number, a missing
ID, a missing name and a duplicate ID." Open **Data issues**: "Instead of
crashing, the app rejects those 8 rows and says exactly which line and why. The
two good rows are still processed."

**6. Testing and next steps (45 seconds)**

Show the terminal: "There are 57 automated tests, including tests that click
through this screen. Next, I'll add Gemini so an administrator can ask 'Who
qualifies for 25%?' in plain English. The important design decision: the AI
only calls my Python functions. It never decides eligibility itself."

## Common interview questions

**Q: Explain your project in one sentence.**
A web app that checks student CGPAs against scholarship rules, assigns each
student the highest tier they qualify for, and flags invalid records, built so
an AI assistant can later be added on top without making decisions itself.

**Q: Why did you split the code into three files?**
Each file has one job. `data_loader.py` reads data, `eligibility.py` makes
decisions, `app.py` displays things. This means I can test the rules without
opening a browser, swap CSV for Google Sheets by changing only the loader, and
let Gemini reuse the same rule functions.

**Q: How do you decide which scholarship a student gets?**
For each student, I keep only the rules whose minimum CGPA they meet, then pick
the one with the highest percentage. If nothing applies, they're "Not eligible".
The comparison is "greater than or equal to", so exactly 8.0 qualifies for 25%.

**Q: What happens if the CSV has bad data?**
Validation runs before any decisions. Each row is checked for a missing ID,
missing name, missing CGPA, non-numeric CGPA, CGPA outside 0 to 10, and
duplicate IDs. Bad rows are removed from the results and shown in a
"Data issues" table with the CSV line number and the reason.

**Q: Why reject both copies of a duplicate student ID instead of keeping one?**
Because the app can't know which record is correct. In my sample, S107 appears
with CGPA 9.30 and 6.10, which means 50% versus nothing. Silently picking one
could give a student the wrong award, so it's safer to ask a human to fix it.

**Q: Why read every column as text first?**
If pandas converted CGPA to numbers while reading, a value like "eleven" would
either crash the load or quietly become blank. Reading as text lets my
validation code see the original value and report a clear reason.

**Q: Why round CGPA to two decimals?**
Computers store decimals approximately, so a value might be 7.999999 instead of
8.0. Rounding to two decimals, which is how CGPA appears on mark sheets, keeps
the threshold comparison fair and predictable. There's a test for it.

**Q: What does "deterministic" mean here, and how did you ensure it?**
Same input, same output, every time. The results are sorted by CGPA and then
student ID, and ties between rules are broken by fixed sort keys. One test
reverses the input order and checks the output is identical.

**Q: How did you test it?**
With pytest. 51 tests cover the rules and data handling: values exactly at a
threshold, just below, the top tier, below all tiers, invalid CGPAs, empty
files, duplicates, search and filters. Six more use Streamlit's AppTest to
type into the search box and change filters, then check what the page shows. I
also checked the tests can fail by temporarily breaking the `>=` rule; four
tests caught it.

**Q: What is Streamlit and why use it?**
A Python library that turns a script into a web page. You write `st.metric` or
`st.dataframe` and it draws the component. It fits a data project because I
don't need to write HTML, CSS or JavaScript, so I can focus on the logic.

**Q: How will you add Gemini without it making things up?**
Using function calling. I describe functions like "find students by
scholarship percentage" to Gemini. When a user asks a question, Gemini replies
with which function to call and with what arguments. My Python code runs the
function and sends the real result back, and Gemini only phrases the answer.
If the question is unclear, like "show the good students", it should ask which
percentage the user means.

**Q: Where will you keep the API key?**
In a `.env` file that is listed in `.gitignore`, so it never reaches GitHub.
The project includes `.env.example` with a placeholder so others know what to
set.

**Q: What are the limitations?**
It uses CGPA only, while real schemes consider income, category or attendance.
Data comes from local CSV files with no editing or login. Those would be the
next things to add for real use.

**Q: What would you do differently at scale?**
Store data in a database instead of CSV, add login so only administrators see
student records, keep an audit log of who changed which rule, and add more
eligibility criteria as separate, tested rule functions.
