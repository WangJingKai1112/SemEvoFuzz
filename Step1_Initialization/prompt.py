from pydantic import BaseModel

class llmFormat(BaseModel):
    code: str

# def llm_prompt() -> str:
#     user_message = (
#         "You are an assistant that helps in generating C code for fuzz testing on the Xuantie C910 processor.\n"
#         "The goal is to generate diverse C code snippets that can be used as test inputs for hardware testing.\n"
#         "Each generated code should be syntactically correct and should cover a variety of C constructs and operations.\n"
#         "The C code should vary in complexity and should contain both simple and advanced constructs to ensure diversity.\n"
#         "Requirements:\n"
#         "1. The code must exhibit high structural diversity and logical complexity.\n"
#         "2. Include multiple control flow structures (conditionals, loops, jumps) while avoiding excessively long loops.\n"
#         "3. Implement varied data type combinations and complex expressions.\n"
#         "4. Maintain strong contextual coherence throughout the code.\n"
#         "5. Incorporate special cases that may trigger boundary conditions.\n"
#         "Prohibited features:\n"
#         "1. Dynamic memory operations (malloc/calloc/realloc/free).\n"
#         "2. Time-related functions (time/gettimeofday).\n"
#         "3. Standard input functions (scanf/fgets/getchar).\n"
#         "4. File I/O operations (fopen/fclose/fread/fwrite).\n"
#         "Please generate a piece of C code."
#     )
#     return user_message

# def llm_prompt() -> str:
#     user_message = (
#         "You are an assistant that helps in generating C code for fuzz testing on the processor.\n"
#         "The goal is to generate diverse C code snippets that can be used as test inputs for hardware testing.\n"
#         "Each generated code should be syntactically correct and should cover a variety of C constructs and operations.\n"
#         "The C code should vary in complexity and should contain both simple and advanced constructs to ensure diversity.\n"
#         "Please generate a piece of C code."
#     )
#     return user_message

def _target_context(target: str = "c910") -> str:
    """Return constraints shared by the generator and target backend.

    The evolutionary operators work on C source for every DUT, but the
    executable environment is not shared: Cascade loads freestanding RV64
    ELF images and provides no libc or console.  Keeping this context in the
    prompt prevents the common generator from producing C910-only helpers.
    """
    target = (target or "c910").lower()
    if target in {"boom", "rocket"}:
        return (
            f"The target is the {target.upper()} Rocket/BOOM-compatible RV64GC "
            "bare-metal harness. The program is linked without libc and runs "
            "without a console, so it must be self-contained: define every "
            "helper it calls, use only standard C operators/types, avoid "
            "stdio/stdlib/POSIX/CSR or platform-specific intrinsics, keep all "
            "loops bounded, and return from main. Do not assume printf output.\n"
        )
    return (
        "The target is the Xuantie C910 RISC-V processor. Keep the program "
        "self-contained and suitable for the existing C910 test harness.\n"
    )


def llm_prompt(target: str = "c910") -> str:
    user_message = (
        "You are an assistant that helps generate C code for processor RTL fuzzing.\n"
        + _target_context(target)
        + "The goal is to generate C programs that exercise DIFFERENT processor hardware features.\n"
        "Each generated code must be syntactically correct, self-contained, and use a DIFFERENT focus area.\n"
        "Vary the focus area across generations to maximize behavioral diversity:\n"
        "- Bounded integer arithmetic (signed/unsigned, overflow scenarios)\n"
        "- Control flow complexity (nested if-else, switch with many cases, goto)\n"
        "- Loop patterns (nested loops, early break/continue, variable bounds)\n"
        "- Array/memory access patterns (sequential, strided, indexed by computation)\n"
        "- Bitwise operations and shifts\n"
        "- Function calls with varying argument counts and return value usage\n"
        "- Mixed data types (int, unsigned, long, short, char, float, double)\n"
        "- Pointer indirection chains\n"
        "Requirements:\n"
        "1. The code must exhibit high structural diversity and logical complexity.\n"
        "2. Include multiple control flow structures while avoiding infinite loops.\n"
        "3. Implement varied data type combinations and complex expressions.\n"
        "4. Incorporate boundary conditions (zero, negative, max/min values).\n"
        "Prohibited features:\n"
        "1. Dynamic memory operations (malloc/calloc/realloc/free).\n"
        "2. Time-related functions (time/gettimeofday).\n"
        "3. Standard input functions (scanf/fgets/getchar).\n"
        "4. File I/O operations (fopen/fclose/fread/fwrite).\n"
        "Please generate a piece of C code focusing on a DIFFERENT aspect than before."
    )
    return user_message


def gap_guided_prompt(gaps: list, target: str = "c910") -> str:
    directions = {
        "LINE": "exercise varied functions, data paths, and instruction sequences",
        "COND": "explore boundary comparisons and varied compound conditions",
        "TOGGLE": (
            "exercise complementary bit patterns such as zero/all-one, single-bit, "
            "alternating, and boundary masks; combine shifts, XOR/AND/OR, mixed "
            "integer widths, variable bit positions, and alternating array or "
            "field writes so that the transformed values reach executed operations"
        ),
        "FSM": (
            "create a bounded multi-stage state machine or state variable whose "
            "transitions depend on prior results; let successive states drive "
            "different conditions, arithmetic, and memory operations across a "
            "terminating sequence rather than merely adding nested branches"
        ),
        "BRANCH": (
            "explore varied control-flow paths using boundary cases, compound "
            "decisions, switch statements, and early exits"
        ),
    }
    focus = "\n".join(
        f"- {gap}: {directions[gap]}" for gap in gaps if gap in directions
    )
    return (
        "You are generating a new C program to introduce fresh behavior into an "
        "evolutionary fuzzing population.\n"
        + _target_context(target)
        + "The current search has stagnated. Its weakest coverage directions are:\n"
        f"{focus}\n"
        "Use these only as broad goals. Explore one or both directions in a novel "
        "way, and choose the program structure and complexity freely.\n"
        "Prefer initialized data, valid memory accesses, and terminating loops. "
        "Avoid relying on undefined behavior where practical.\n"
        "The program must be self-contained and syntactically correct. Do not use "
        "dynamic memory allocation, time functions, standard input, or file I/O.\n"
        "Return one complete C program."
    )
