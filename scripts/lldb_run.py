"""Run somesay.exe under lldb, break on abort(), dump all thread backtraces."""
import lldb
import sys

debugger = lldb.SBDebugger()
target = debugger.CreateTarget("runtime/build/somesay.exe", "windows", True)
if not target:
    print("Failed to create target")
    sys.exit(1)

target.AppendArguments("--rom", "rom/game.z64")

breakpoint = target.BreakpointCreateByName("abort", None)
print(f"Breakpoint set: id={breakpoint.id}, locs={breakpoint.num_locations}")

process = target.Launch(debugger, None)
print(f"Process launched: valid={process.is_valid}")

if process.is_valid:
    # Wait for the process to stop (at breakpoint or crash)
    while True:
        event = lldb.SBEvent()
        if debugger.RunEvent(event):
            pass
        state = process.GetState()
        if state not in (lldb.eStateLaunching, lldb.eStateRunning):
            break

    print(f"\nProcess state: {state}")

    # Get backtrace of all threads
    num_threads = process.GetNumThreads()
    print(f"Active threads: {num_threads}")
    for i in range(num_threads):
        thread = process.GetThreadAtIndex(i)
        tid = thread.GetID()
        tname = thread.GetName() if thread.IsValid() else "unknown"
        num_frames = thread.GetNumFrames() if thread.IsValid() else 0
        print(f"\n--- Thread #{tid} ({tname}) ---")
        for j in range(num_frames):
            frame = thread.GetFrameAtIndex(j)
            fname = frame.GetFunctionName() if frame.IsValid() else "?"
            fnamesrc = frame.GetFileSpec().GetFilename() if frame.IsValid() else "?"
            line_no = frame.GetLine() if frame.IsValid() else 0
            print(f"  #{j}: {fname} in {fnamesrc}:{line_no}")

debugger.Terminate()
