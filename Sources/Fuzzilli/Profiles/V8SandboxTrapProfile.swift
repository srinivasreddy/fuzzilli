// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/// SbxBrk-style sandbox profile using V8's trap-based sandbox fuzzer.
///
/// This profile requires a V8 build with:
///   v8_enable_sandbox=true
///   v8_enable_memory_corruption_api=true
///   v8_enable_sandbox_hardware_support=true
/// and trace-pc-guard coverage. The trap fuzzer uses memory protection keys and
/// mutations on sandbox accesses; it requires --single-threaded and, unlike
/// explicit API corruption, its crashes are generally not reproducible. Use the
/// `v8Sandbox` profile for the deterministic Memory-Corruption-API baseline.
public let v8SandboxTrapProfile = Profile(
    processArgs: { randomize, isWasmEnabled in
        var args = v8ProcessArgs(
            randomize: randomize, isWasmEnabled: isWasmEnabled, forSandbox: true)
        args.append("--sandbox-trap-fuzzing")
        args.append("--single-threaded")
        return args
    },

    processArgsReference: nil,

    processEnv: [
        "ASAN_OPTIONS": "abort_on_error=1:handle_sigill=1:symbolize=false:redzone=128",
        "UBSAN_OPTIONS": "abort_on_error=1:symbolize=false:redzone=128",
    ],

    maxExecsBeforeRespawn: 1000,

    timeout: Timeout.interval(500, 1200),

    codePrefix: "",

    codeSuffix: "",

    ecmaVersion: ECMAScriptVersion.es6,

    startupTests: [
        ("fuzzilli('FUZZILLI_PRINT', 'test')", .shouldSucceed),
        ("Sandbox.getAddressOf([1, 2, 3])", .shouldSucceed),
        ("fuzzilli('FUZZILLI_CRASH', 9)", .shouldCrash),
    ],

    additionalCodeGenerators: [
        (ForceJITCompilationThroughLoopGenerator, 5),
        (ForceTurboFanCompilationGenerator, 15),
        (ForceMaglevCompilationGenerator, 15),
        (ForceWasmTurboFanCompilationGenerator, 5),
        (CompileBaselineGenerator, 10),
        (ForceOsrGenerator, 10),
        (NeverOptimizeFunctionGenerator, 5),
        (DisableEagerInliningGenerator, 5),
        (DeoptimizeFunctionGenerator, 5),
        (DeoptimizeNowGenerator, 5),
        (SetForceSlowPathGenerator, 5),
        (V8GcGenerator, 10),
        (V8DispatchTableGCIntervalGenerator, 5),
        (V8SimulateNewspaceFullGenerator, 5),
    ],

    additionalProgramTemplates: WeightedList<ProgramTemplate>([]),

    disabledCodeGenerators: [],

    disabledMutators: [],

    additionalBuiltins: [
        "gc": .function([.opt(gcOptions.instanceType)] => (.undefined | .jsPromise())),
        "d8": .jsD8,
    ],

    additionalObjectGroups: [jsD8, jsD8Test, gcOptions],

    additionalEnumerations: [.gcTypeEnum, .gcExecutionEnum],

    additionalOptionsBags: [],

    optionalPostProcessor: nil
)
