import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.PrintStream;
import java.lang.reflect.Array;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Command-line foundation for loading a student's compiled target class. */
public final class ReflectionJudge {
    private static final int MAX_SPEC_BYTES = 1024 * 1024;
    private static final int MAX_JSON_DEPTH = 64;
    private static final int MAX_POINT_PRECISION = 1000;
    private static final int MAX_POINT_SCALE = 1000;
    private static final String INVALID_REQUEST = "INVALID_REQUEST";
    private static final String PROTOCOL_ERROR = "PROTOCOL_ERROR";
    private static final String JUDGE_INFRA_ERROR = "JUDGE_INFRA_ERROR";
    private static final String CLASS_LOADING_FAILURE = "CLASS_LOADING_FAILURE";
    private static final String STUDENT_EXCEPTION = "STUDENT_EXCEPTION";

    private ReflectionJudge() {}

    public static void main(String[] args) {
        PrintStream protocolOut = System.out;
        ProtocolChannel protocol = new ProtocolChannel(protocolOut);
        PrintStream capturedStudentOut = new PrintStream(
                new DiscardingOutputStream(), true, StandardCharsets.UTF_8);
        Thread shutdownHook = new Thread(protocol::writeEmergencyResponse, "judge-protocol-shutdown");
        try {
            Runtime.getRuntime().addShutdownHook(shutdownHook);
        } catch (IllegalStateException | SecurityException error) {
            protocol.write(Response.failure(
                    BigDecimal.ZERO, List.of(), JUDGE_INFRA_ERROR, null,
                    "Could not register the Judge shutdown handler."));
            return;
        }
        Response response;
        try {
            System.setOut(capturedStudentOut);
            response = execute(args, protocol);
        } catch (Throwable error) {
            response = Response.failure(
                    BigDecimal.ZERO,
                    List.of(),
                    JUDGE_INFRA_ERROR,
                    null,
                    safeMessage(error));
        } finally {
            // Keep System.out attached to the discard stream. A student static
            // initializer may start a thread that writes after class loading.
            try {
                System.setOut(capturedStudentOut);
            } catch (SecurityException ignored) {
                // The saved protocol stream below remains independent of System.out.
            }
        }
        protocol.write(response);
    }

    private static Response execute(String[] args, ProtocolChannel protocol) {
        if (args == null || args.length != 2) {
            return Response.failure(
                    BigDecimal.ZERO, List.of(), INVALID_REQUEST, null,
                    "Expected arguments: <target-class-name> <student-output-directory>.");
        }

        String targetClassName = args[0];
        if (!isBinaryClassName(targetClassName)) {
            return Response.failure(
                    BigDecimal.ZERO, List.of(), INVALID_REQUEST, null,
                    "Target class name is invalid.");
        }

        final Spec spec;
        try {
            spec = readAndValidateSpec(System.in);
        } catch (InvalidSpecificationException error) {
            return Response.failure(
                    BigDecimal.ZERO, List.of(), INVALID_REQUEST, null, error.getMessage());
        } catch (ProtocolInputException error) {
            return Response.failure(
                    BigDecimal.ZERO, List.of(), PROTOCOL_ERROR, null, error.getMessage());
        }

        final Path studentOutput;
        try {
            studentOutput = Path.of(args[1]).toRealPath();
            if (!Files.isDirectory(studentOutput)) {
                return Response.failure(
                        spec.totalPoints, failedChecks(spec, INVALID_REQUEST + ": invalid output directory"),
                        INVALID_REQUEST, null,
                        "Student output path is not a directory.");
            }
        } catch (IOException | SecurityException | java.nio.file.InvalidPathException error) {
            return Response.failure(
                    spec.totalPoints, failedChecks(spec, INVALID_REQUEST + ": invalid output directory"),
                    INVALID_REQUEST, null,
                    "Student output directory cannot be accessed.");
        }

        protocol.armForStudentExecution(spec);
        try {
            return loadTargetClassAndRunChecks(targetClassName, studentOutput, spec);
        } catch (ClassNotFoundException error) {
            String message = "Target class '" + targetClassName
                    + "' was not found in the student output directory.";
            return Response.failure(
                    spec.totalPoints,
                    failedChecks(spec, CLASS_LOADING_FAILURE + ": " + message),
                    null,
                    CLASS_LOADING_FAILURE,
                    message);
        } catch (ExceptionInInitializerError error) {
            String message = "Student class initialization failed: " + safeMessage(error.getCause() == null
                    ? error : error.getCause());
            return Response.failure(
                    spec.totalPoints,
                    failedChecks(spec, STUDENT_EXCEPTION + ": " + message),
                    null,
                    STUDENT_EXCEPTION,
                    message);
        } catch (LinkageError | SecurityException error) {
            String message = "Target class could not be loaded: " + safeMessage(error);
            return Response.failure(
                    spec.totalPoints,
                    failedChecks(spec, CLASS_LOADING_FAILURE + ": " + message),
                    null,
                    CLASS_LOADING_FAILURE,
                    message);
        } catch (IOException error) {
            return Response.failure(
                    spec.totalPoints,
                    failedChecks(spec, JUDGE_INFRA_ERROR + ": class loader cleanup failed"),
                    JUDGE_INFRA_ERROR,
                    null,
                    "Judge could not close the student class loader.");
        } catch (Throwable error) {
            return Response.failure(
                    spec.totalPoints,
                    failedChecks(spec, JUDGE_INFRA_ERROR + ": " + safeMessage(error)),
                    JUDGE_INFRA_ERROR,
                    null,
                    "Judge failed while loading the target class: " + safeMessage(error));
        }
    }

    private static Response loadTargetClassAndRunChecks(
            String targetClassName, Path studentOutput, Spec spec)
            throws IOException, ClassNotFoundException {
        URL studentDirectory = studentOutput.toUri().toURL();
        try (URLClassLoader loader = new URLClassLoader(
                new URL[] {studentDirectory}, ClassLoader.getPlatformClassLoader())) {
            Class<?> target = Class.forName(targetClassName, false, loader);
            if (target.getClassLoader() != loader) {
                throw new ClassNotFoundException(
                        "Target class was resolved by a parent loader, not student output.");
            }
            Class.forName(targetClassName, true, loader);
            return runChecks(target, loader, spec);
        }
    }

    private static Spec readAndValidateSpec(InputStream input)
            throws InvalidSpecificationException, ProtocolInputException {
        byte[] bytes;
        try {
            bytes = readBounded(input, MAX_SPEC_BYTES);
        } catch (IOException error) {
            throw new ProtocolInputException("Could not read specification from stdin.");
        }

        final String json;
        try {
            json = StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes))
                    .toString();
        } catch (CharacterCodingException error) {
            throw new InvalidSpecificationException("Specification is not valid UTF-8.");
        }

        Object parsed;
        try {
            parsed = new JsonParser(json).parse();
        } catch (InvalidSpecificationException error) {
            throw error;
        }
        if (!(parsed instanceof Map)) {
            throw new InvalidSpecificationException("Specification must be a JSON object.");
        }

        Map<?, ?> root = (Map<?, ?>) parsed;
        Object rawChecks = root.get("checks");
        if (!(rawChecks instanceof List)) {
            throw new InvalidSpecificationException("Specification must contain a checks array.");
        }

        List<SpecCheck> checks = new ArrayList<>();
        Set<String> ids = new HashSet<>();
        BigDecimal sum = BigDecimal.ZERO;
        int index = 0;
        for (Object rawCheck : (List<?>) rawChecks) {
            if (!(rawCheck instanceof Map)) {
                throw new InvalidSpecificationException("Check at index " + index + " must be an object.");
            }
            Map<?, ?> check = (Map<?, ?>) rawCheck;
            Object rawId = check.get("id");
            Object rawKind = check.get("kind");
            Object rawPoints = check.get("points");
            if (!(rawId instanceof String) || ((String) rawId).isBlank()) {
                throw new InvalidSpecificationException("Check at index " + index + " needs a non-empty id.");
            }
            String id = (String) rawId;
            if (!ids.add(id)) {
                throw new InvalidSpecificationException("Duplicate check id: " + id + ".");
            }
            if (!(rawKind instanceof String) || ((String) rawKind).isBlank()) {
                throw new InvalidSpecificationException("Check '" + id + "' needs a non-empty kind.");
            }
            if (!(rawPoints instanceof BigDecimal)) {
                throw new InvalidSpecificationException("Check '" + id + "' needs numeric points.");
            }
            BigDecimal points = (BigDecimal) rawPoints;
            validatePoints(points, "Check '" + id + "' points");
            Object visible = check.get("is_visible");
            if (!check.containsKey("is_visible") || !(visible instanceof Boolean)) {
                throw new InvalidSpecificationException("Check '" + id + "' is_visible must be a boolean.");
            }
            Map<String, Object> properties = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : check.entrySet()) {
                properties.put((String) entry.getKey(), entry.getValue());
            }
            checks.add(new SpecCheck(id, (String) rawKind, points, properties));
            sum = sum.add(points);
            index++;
        }

        Object rawTotalPoints = root.get("total_points");
        if (!(rawTotalPoints instanceof BigDecimal)) {
            throw new InvalidSpecificationException("total_points must be numeric.");
        }
        BigDecimal declaredTotal = (BigDecimal) rawTotalPoints;
        validatePoints(declaredTotal, "total_points");
        if (declaredTotal.compareTo(sum) != 0) {
            throw new InvalidSpecificationException(
                    "total_points must equal the sum of check points.");
        }
        return new Spec(checks, sum);
    }

    private static void validatePoints(BigDecimal points, String field)
            throws InvalidSpecificationException {
        if (points.signum() < 0) {
            throw new InvalidSpecificationException(field + " cannot be negative.");
        }
        if (points.precision() > MAX_POINT_PRECISION
                || Math.abs((long) points.scale()) > MAX_POINT_SCALE) {
            throw new InvalidSpecificationException(field + " exceeds the supported numeric range.");
        }
    }

    private static byte[] readBounded(InputStream input, int limit) throws IOException,
            InvalidSpecificationException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        byte[] buffer = new byte[4096];
        int count;
        while ((count = input.read(buffer)) != -1) {
            if (bytes.size() + count > limit) {
                throw new InvalidSpecificationException("Specification exceeds the size limit.");
            }
            bytes.write(buffer, 0, count);
        }
        return bytes.toByteArray();
    }

    private static boolean isBinaryClassName(String name) {
        if (name == null || name.isBlank()) {
            return false;
        }
        String[] parts = name.split("\\.", -1);
        for (String part : parts) {
            if (part.isEmpty() || !Character.isJavaIdentifierStart(part.charAt(0))) {
                return false;
            }
            for (int index = 1; index < part.length(); index++) {
                if (!Character.isJavaIdentifierPart(part.charAt(index))) {
                    return false;
                }
            }
        }
        return true;
    }

    private static List<CheckResult> failedChecks(Spec spec, String message) {
        List<CheckResult> results = new ArrayList<>();
        for (SpecCheck check : spec.checks) {
            results.add(CheckResult.failed(
                    check, check.expectedDescription(), "<target class unavailable>", message));
        }
        return results;
    }

    private static Response runChecks(Class<?> target, ClassLoader loader, Spec spec) {
        List<CheckResult> results = new ArrayList<>();
        BigDecimal score = BigDecimal.ZERO;
        for (SpecCheck check : spec.checks) {
            CheckResult result = evaluateCheck(check, target, loader);
            results.add(result);
            score = score.add(result.pointsEarned);
        }
        return Response.success(score, spec.totalPoints, results);
    }

    private static CheckResult evaluateCheck(SpecCheck check, Class<?> target, ClassLoader loader) {
        String expected = check.expectedDescription();
        try {
            switch (check.kind) {
                case "field":
                    return evaluateField(check, target, loader);
                case "constructor":
                    return evaluateConstructor(check, target, loader);
                case "method":
                    return evaluateMethod(check, target, loader);
                case "implements":
                    return evaluateImplements(check, target, loader);
                case "behavior":
                    return evaluateBehavior(check, target, loader);
                case "toString":
                    return evaluateToString(check, target, loader);
                case "comparable":
                    return evaluateComparable(check, target, loader);
                default:
                    return CheckResult.failed(
                            check, expected, null, "UNSUPPORTED_CHECK_KIND: " + check.kind);
            }
        } catch (CheckSpecificationException error) {
            return CheckResult.failed(
                    check, expected, null, "INVALID_CHECK_SPEC: " + error.getMessage());
        } catch (CheckFailure error) {
            return CheckResult.failed(check, expected, error.actual, error.code);
        } catch (Throwable error) {
            return CheckResult.failed(check, expected, null, "CHECK_ERROR: " + safeMessage(error));
        }
    }

    private static CheckResult evaluateField(
            SpecCheck check, Class<?> target, ClassLoader loader)
            throws CheckSpecificationException {
        String name = requiredString(check, "name");
        String expectedTypeName = requiredString(check, "type");
        Set<String> expectedModifiers = requiredModifiers(check, "field");
        Class<?> expectedType = resolveType(expectedTypeName, target, loader, false);
        String expected = "name=" + name + ", type=" + expectedTypeName
                + ", modifier=" + check.properties.get("modifier");

        final Field field;
        try {
            field = target.getDeclaredField(name);
        } catch (NoSuchFieldException error) {
            return CheckResult.failed(check, expected, "<field not found>", "FIELD_NOT_FOUND");
        }
        String actual = "name=" + field.getName() + ", type=" + field.getType().getTypeName()
                + ", modifier=" + modifierText(field.getModifiers(), false);
        boolean passed = field.getType().equals(expectedType)
                && actualModifiers(field.getModifiers(), false).equals(expectedModifiers);
        return CheckResult.evaluated(check, passed, expected, actual, null);
    }

    private static CheckResult evaluateConstructor(
            SpecCheck check, Class<?> target, ClassLoader loader)
            throws CheckSpecificationException {
        List<String> parameterNames = requiredTypeList(check, "parameter_types");
        Class<?>[] parameterTypes = resolveParameterTypes(parameterNames, target, loader);
        Set<String> expectedModifiers = requiredModifiers(check, "constructor");
        String expected = "parameter_types=" + parameterNames + ", modifier="
                + check.properties.get("modifier");

        final Constructor<?> constructor;
        try {
            constructor = target.getDeclaredConstructor(parameterTypes);
        } catch (NoSuchMethodException error) {
            return CheckResult.failed(
                    check, expected, "available=" + availableConstructors(target), "CONSTRUCTOR_NOT_FOUND");
        }
        String actual = "parameter_types=" + parameterTypeNames(constructor.getParameterTypes())
                + ", modifier=" + modifierText(constructor.getModifiers(), false);
        boolean passed = actualModifiers(constructor.getModifiers(), false).equals(expectedModifiers);
        return CheckResult.evaluated(check, passed, expected, actual, null);
    }

    private static CheckResult evaluateMethod(
            SpecCheck check, Class<?> target, ClassLoader loader)
            throws CheckSpecificationException {
        String name = requiredString(check, "name");
        String expectedReturnName = requiredString(check, "return_type");
        List<String> parameterNames = requiredTypeList(check, "parameter_types");
        Set<String> expectedModifiers = requiredModifiers(check, "method");
        Class<?> expectedReturnType = resolveType(expectedReturnName, target, loader, true);
        Class<?>[] parameterTypes = resolveParameterTypes(parameterNames, target, loader);
        String expected = "name=" + name + ", parameter_types=" + parameterNames
                + ", return_type=" + expectedReturnName + ", modifier="
                + check.properties.get("modifier");

        final Method method;
        try {
            method = target.getDeclaredMethod(name, parameterTypes);
        } catch (NoSuchMethodException error) {
            return CheckResult.failed(
                    check, expected, "available=" + availableMethods(target, name), "METHOD_NOT_FOUND");
        }
        String actual = describeMethod(method);
        boolean passed = method.getReturnType().equals(expectedReturnType)
                && actualModifiers(method.getModifiers(), method.isDefault()).equals(expectedModifiers);
        return CheckResult.evaluated(check, passed, expected, actual, null);
    }

    private static CheckResult evaluateImplements(
            SpecCheck check, Class<?> target, ClassLoader loader)
            throws CheckSpecificationException {
        String interfaceName = requiredString(check, "interface");
        Class<?> interfaceType = resolveType(interfaceName, target, loader, false);
        if (!interfaceType.isInterface()) {
            throw new CheckSpecificationException("'" + interfaceName + "' is not an interface.");
        }
        boolean passed = interfaceType.isAssignableFrom(target);
        String expected = "implements " + interfaceName;
        String actual = "implemented=" + passed + ", direct_interfaces=" + directInterfaceNames(target);
        return CheckResult.evaluated(check, passed, expected, actual, null);
    }

    private static CheckResult evaluateBehavior(
            SpecCheck check, Class<?> target, ClassLoader loader)
            throws CheckSpecificationException, CheckFailure {
        boolean expectsReturn = check.properties.containsKey("expect_return");
        boolean expectsState = check.properties.containsKey("expect_state");
        boolean expectsException = check.properties.containsKey("expect_exception");
        if (!expectsReturn && !expectsState && !expectsException) {
            throw new CheckSpecificationException(
                    "behavior needs expect_return, expect_state, or expect_exception.");
        }
        if (expectsException && (expectsReturn || expectsState)) {
            throw new CheckSpecificationException(
                    "expect_exception cannot be combined with return/state expectations.");
        }

        requiredString(check, "method");
        String expected = check.expectedDescription();
        Object instance = instantiateTarget(target, loader, check.properties);
        runSetup(instance, target, loader, check.properties);
        InvocationOutcome outcome = invokeConfiguredMethod(
                instance, target, loader, check.properties, "method", "args", "parameter_types");

        if (outcome.invocationError) {
            return CheckResult.failed(
                    check, expected, exceptionText(outcome.exception), "METHOD_INVOCATION_ERROR");
        }

        if (expectsException) {
            String exceptionName = requiredString(check, "expect_exception");
            Class<?> expectedException = resolveType(exceptionName, target, loader, false);
            if (!Throwable.class.isAssignableFrom(expectedException)) {
                throw new CheckSpecificationException("expect_exception must name a Throwable type.");
            }
            String expectedMessage = optionalString(check.properties, "expect_exception_message");
            Throwable thrown = outcome.exception;
            boolean passed = thrown != null && expectedException.isInstance(thrown)
                    && (expectedMessage == null || expectedMessage.equals(thrown.getMessage()));
            String actual = thrown == null
                    ? "returned " + jsonText(toJsonValue(outcome.value))
                    : exceptionText(thrown);
            String error = thrown == null ? "EXPECTED_EXCEPTION_NOT_THROWN"
                    : (passed ? null : "UNEXPECTED_EXCEPTION");
            return CheckResult.evaluated(check, passed, expected, actual, error);
        }

        if (outcome.exception != null) {
            return CheckResult.failed(check, expected, exceptionText(outcome.exception), "UNEXPECTED_EXCEPTION");
        }

        boolean passed = true;
        List<String> actualParts = new ArrayList<>();
        if (expectsReturn) {
            Object actualReturn = toJsonValue(outcome.value);
            passed &= valuesEqual(check.properties.get("expect_return"), actualReturn);
            actualParts.add("return=" + jsonText(actualReturn));
        }
        if (expectsState) {
            Map<?, ?> stateSpec = requireObject(check.properties.get("expect_state"), "expect_state");
            Object expectedState = requiredProperty(stateSpec, "value");
            Object actualState = readExpectedState(instance, target, loader, stateSpec);
            Object jsonState = toJsonValue(actualState);
            passed &= valuesEqual(expectedState, jsonState);
            actualParts.add("state=" + jsonText(jsonState));
        }
        return CheckResult.evaluated(check, passed, expected, String.join("; ", actualParts), null);
    }

    private static CheckResult evaluateToString(
            SpecCheck check, Class<?> target, ClassLoader loader)
            throws CheckSpecificationException, CheckFailure {
        String template = requiredString(check, "template");
        Object instance = instantiateTarget(target, loader, check.properties);
        runSetup(instance, target, loader, check.properties);
        String expected = expandStringTemplate(template, instance, target);

        final Method toStringMethod;
        try {
            toStringMethod = target.getMethod("toString");
        } catch (NoSuchMethodException error) {
            throw new CheckFailure("TOSTRING_METHOD_NOT_FOUND", "<toString() not found>");
        }
        InvocationOutcome outcome = invokeMethod(toStringMethod, instance, new Object[0]);
        if (outcome.exception != null) {
            return CheckResult.failed(
                    check,
                    expected,
                    exceptionText(outcome.exception),
                    outcome.invocationError ? "TOSTRING_INVOCATION_ERROR" : "TOSTRING_EXCEPTION");
        }
        String actual = String.valueOf(outcome.value);
        String normalizedExpected = normalizeNewlines(expected);
        String normalizedActual = normalizeNewlines(actual);
        return CheckResult.evaluated(
                check, normalizedExpected.equals(normalizedActual), normalizedExpected, normalizedActual, null);
    }

    private static CheckResult evaluateComparable(
            SpecCheck check, Class<?> target, ClassLoader loader)
            throws CheckSpecificationException, CheckFailure {
        if (!Comparable.class.isAssignableFrom(target)) {
            throw new CheckFailure("NOT_COMPARABLE", "<Comparable is not implemented>");
        }
        List<?> rawInstances = requiredArray(check.properties, "instances");
        if (rawInstances.size() < 2) {
            throw new CheckSpecificationException("comparable needs at least two instances.");
        }
        List<Object> instances = new ArrayList<>();
        for (int index = 0; index < rawInstances.size(); index++) {
            Map<?, ?> instanceSpec = requireObject(rawInstances.get(index), "instances[" + index + "]");
            Object instance = instantiateTarget(target, loader, instanceSpec);
            runSetup(instance, target, loader, instanceSpec);
            instances.add(instance);
        }

        List<?> comparisons = optionalArray(check.properties, "comparisons");
        boolean hasExpectedOrder = check.properties.containsKey("expected_order");
        if (comparisons.isEmpty() && !hasExpectedOrder) {
            throw new CheckSpecificationException("comparable needs comparisons or expected_order.");
        }
        List<String> expectedParts = new ArrayList<>();
        List<String> actualParts = new ArrayList<>();
        boolean passed = true;
        Method compareTo = comparableMethod();
        for (int index = 0; index < comparisons.size(); index++) {
            Map<?, ?> comparison = requireObject(comparisons.get(index), "comparisons[" + index + "]");
            int left = requiredIndex(comparison, "left", instances.size());
            int right = requiredIndex(comparison, "right", instances.size());
            int expectedSign = requiredSign(comparison, "expected_sign");
            Object rawResult = invokeComparable(compareTo, instances.get(left), instances.get(right));
            int actualSign = Integer.signum(((Number) rawResult).intValue());
            expectedParts.add(left + " vs " + right + "=" + expectedSign);
            actualParts.add(left + " vs " + right + "=" + actualSign);
            passed &= expectedSign == actualSign;
        }

        if (hasExpectedOrder) {
            List<Integer> expectedOrder = requiredIndexList(
                    check.properties.get("expected_order"), "expected_order", instances.size());
            List<Integer> actualOrder = new ArrayList<>();
            for (int index = 0; index < instances.size(); index++) {
                actualOrder.add(index);
            }
            try {
                actualOrder.sort((left, right) -> {
                    try {
                        return ((Number) invokeComparable(
                                compareTo, instances.get(left), instances.get(right))).intValue();
                    } catch (CheckFailure error) {
                        throw new ComparableCheckRuntimeException(error);
                    }
                });
            } catch (ComparableCheckRuntimeException error) {
                throw error.failure;
            }
            expectedParts.add("order=" + expectedOrder);
            actualParts.add("order=" + actualOrder);
            passed &= expectedOrder.equals(actualOrder);
        }

        return CheckResult.evaluated(
                check,
                passed,
                String.join("; ", expectedParts),
                String.join("; ", actualParts),
                null);
    }

    private static Object readExpectedState(
            Object instance, Class<?> target, ClassLoader loader, Map<?, ?> stateSpec)
            throws CheckSpecificationException, CheckFailure {
        requiredProperty(stateSpec, "value");
        boolean hasGetter = stateSpec.containsKey("getter");
        boolean hasField = stateSpec.containsKey("field");
        if (hasGetter == hasField) {
            throw new CheckSpecificationException("expect_state needs exactly one of getter or field.");
        }
        if (hasGetter) {
            Map<String, Object> getterSpec = new LinkedHashMap<>();
            getterSpec.put("method", stateSpec.get("getter"));
            getterSpec.put("args", stateSpec.containsKey("args") ? stateSpec.get("args") : List.of());
            if (stateSpec.containsKey("parameter_types")) {
                getterSpec.put("parameter_types", stateSpec.get("parameter_types"));
            }
            InvocationOutcome outcome = invokeConfiguredMethod(
                    instance, target, loader, getterSpec, "method", "args", "parameter_types");
            if (outcome.exception != null) {
                String errorCode = outcome.invocationError
                        ? "STATE_GETTER_INVOCATION_ERROR" : "STATE_GETTER_EXCEPTION";
                throw new CheckFailure(errorCode + ": " + exceptionText(outcome.exception),
                        exceptionText(outcome.exception));
            }
            return outcome.value;
        }

        Object rawFieldName = stateSpec.get("field");
        if (!(rawFieldName instanceof String) || ((String) rawFieldName).isBlank()) {
            throw new CheckSpecificationException("expect_state.field must be a non-empty string.");
        }
        try {
            Field field = target.getDeclaredField((String) rawFieldName);
            field.setAccessible(true);
            return field.get(instance);
        } catch (NoSuchFieldException error) {
            throw new CheckFailure("STATE_FIELD_NOT_FOUND", "<field not found>");
        } catch (IllegalAccessException error) {
            throw new CheckFailure("STATE_FIELD_ACCESS_ERROR", safeMessage(error));
        }
    }

    private static Object instantiateTarget(
            Class<?> target, ClassLoader loader, Map<?, ?> specification)
            throws CheckSpecificationException, CheckFailure {
        List<?> args = optionalArray(specification, "constructor_args");
        final Constructor<?> constructor;
        if (specification.containsKey("constructor_parameter_types")) {
            List<String> names = requiredTypeList(specification, "constructor_parameter_types");
            Class<?>[] parameterTypes = resolveParameterTypes(names, target, loader);
            try {
                constructor = target.getDeclaredConstructor(parameterTypes);
            } catch (NoSuchMethodException error) {
                throw new CheckFailure("CONSTRUCTOR_NOT_FOUND", "available=" + availableConstructors(target));
            }
            if (parameterTypes.length != args.size()) {
                throw new CheckSpecificationException("constructor_args length must match constructor_parameter_types.");
            }
        } else {
            List<Constructor<?>> candidates = new ArrayList<>();
            for (Constructor<?> candidate : target.getDeclaredConstructors()) {
                if (candidate.getParameterCount() == args.size()) {
                    try {
                        convertArguments(args, candidate.getParameterTypes());
                        candidates.add(candidate);
                    } catch (CheckSpecificationException ignored) {
                        // This overload cannot accept the supplied JSON values.
                    }
                }
            }
            if (candidates.isEmpty()) {
                throw new CheckFailure("CONSTRUCTOR_NOT_FOUND", "available=" + availableConstructors(target));
            }
            if (candidates.size() != 1) {
                throw new CheckSpecificationException(
                        "constructor_args match multiple overloads; supply constructor_parameter_types.");
            }
            constructor = candidates.get(0);
        }

        Object[] arguments = convertArguments(args, constructor.getParameterTypes());
        try {
            constructor.setAccessible(true);
            return constructor.newInstance(arguments);
        } catch (InvocationTargetException error) {
            Throwable cause = unwrapInvocation(error);
            throw new CheckFailure("CONSTRUCTOR_EXCEPTION: " + exceptionText(cause), exceptionText(cause));
        } catch (ReflectiveOperationException | SecurityException error) {
            throw new CheckFailure("CONSTRUCTOR_ERROR: " + safeMessage(error), safeMessage(error));
        }
    }

    private static void runSetup(
            Object instance, Class<?> target, ClassLoader loader, Map<?, ?> specification)
            throws CheckSpecificationException, CheckFailure {
        List<?> setup = optionalArray(specification, "setup");
        for (int index = 0; index < setup.size(); index++) {
            Map<?, ?> action = requireObject(setup.get(index), "setup[" + index + "]");
            InvocationOutcome outcome = invokeConfiguredMethod(
                    instance, target, loader, action, "method", "args", "parameter_types");
            if (outcome.exception != null) {
                String errorCode = outcome.invocationError ? "SETUP_INVOCATION_ERROR" : "SETUP_EXCEPTION";
                throw new CheckFailure(errorCode + ": " + exceptionText(outcome.exception),
                        exceptionText(outcome.exception));
            }
        }
    }

    private static InvocationOutcome invokeConfiguredMethod(
            Object instance,
            Class<?> target,
            ClassLoader loader,
            Map<?, ?> specification,
            String methodKey,
            String argsKey,
            String parameterTypesKey)
            throws CheckSpecificationException, CheckFailure {
        Object rawName = specification.get(methodKey);
        if (!(rawName instanceof String) || ((String) rawName).isBlank()) {
            throw new CheckSpecificationException("'" + methodKey + "' must be a non-empty string.");
        }
        List<?> args = optionalArray(specification, argsKey);
        Method method = resolveBehaviorMethod(
                target, loader, (String) rawName, args, specification.get(parameterTypesKey),
                specification.containsKey(parameterTypesKey));
        Object[] converted = convertArguments(args, method.getParameterTypes());
        try {
            method.setAccessible(true);
            return invokeMethod(method, instance, converted);
        } catch (SecurityException error) {
            throw new CheckFailure("METHOD_ACCESS_ERROR: " + safeMessage(error), safeMessage(error));
        }
    }

    private static Method resolveBehaviorMethod(
            Class<?> target,
            ClassLoader loader,
            String name,
            List<?> args,
            Object rawParameterTypes,
            boolean parameterTypesSpecified)
            throws CheckSpecificationException, CheckFailure {
        if (parameterTypesSpecified) {
            List<String> names = requiredTypeListValue(rawParameterTypes, "parameter_types");
            Class<?>[] parameterTypes = resolveParameterTypes(names, target, loader);
            if (parameterTypes.length != args.size()) {
                throw new CheckSpecificationException("args length must match parameter_types.");
            }
            try {
                return target.getDeclaredMethod(name, parameterTypes);
            } catch (NoSuchMethodException error) {
                throw new CheckFailure("METHOD_NOT_FOUND", "available=" + availableMethods(target, name));
            }
        }

        List<Method> candidates = new ArrayList<>();
        for (Method candidate : target.getDeclaredMethods()) {
            if (candidate.getName().equals(name) && candidate.getParameterCount() == args.size()) {
                try {
                    convertArguments(args, candidate.getParameterTypes());
                    candidates.add(candidate);
                } catch (CheckSpecificationException ignored) {
                    // This overload cannot accept the supplied JSON values.
                }
            }
        }
        if (candidates.isEmpty()) {
            throw new CheckFailure("METHOD_NOT_FOUND", "available=" + availableMethods(target, name));
        }
        if (candidates.size() != 1) {
            throw new CheckSpecificationException(
                    "arguments match multiple method overloads; supply parameter_types.");
        }
        return candidates.get(0);
    }

    private static InvocationOutcome invokeMethod(Method method, Object target, Object[] arguments) {
        try {
            return new InvocationOutcome(method.invoke(target, arguments), null, false);
        } catch (InvocationTargetException error) {
            return new InvocationOutcome(null, unwrapInvocation(error), false);
        } catch (IllegalAccessException | IllegalArgumentException error) {
            return new InvocationOutcome(null, error, true);
        }
    }

    private static Throwable unwrapInvocation(Throwable error) {
        Throwable current = error;
        while (current instanceof InvocationTargetException
                && ((InvocationTargetException) current).getCause() != null) {
            current = ((InvocationTargetException) current).getCause();
        }
        return current;
    }

    private static String exceptionText(Throwable error) {
        Throwable cause = unwrapInvocation(error);
        String message = cause.getMessage();
        return cause.getClass().getName() + (message == null ? "" : ": " + message);
    }

    private static Object[] convertArguments(List<?> args, Class<?>[] parameterTypes)
            throws CheckSpecificationException {
        if (args.size() != parameterTypes.length) {
            throw new CheckSpecificationException("argument count does not match method parameter count.");
        }
        Object[] result = new Object[args.size()];
        for (int index = 0; index < args.size(); index++) {
            result[index] = convertArgument(args.get(index), parameterTypes[index]);
        }
        return result;
    }

    private static Object convertArgument(Object value, Class<?> targetType)
            throws CheckSpecificationException {
        if (value == null) {
            if (targetType.isPrimitive()) {
                throw new CheckSpecificationException("null cannot be passed to a primitive parameter.");
            }
            return null;
        }
        if (targetType.isArray()) {
            if (!(value instanceof List)) {
                throw new CheckSpecificationException("array parameters require a JSON array value.");
            }
            List<?> values = (List<?>) value;
            Object array = Array.newInstance(targetType.getComponentType(), values.size());
            for (int index = 0; index < values.size(); index++) {
                Array.set(array, index, convertArgument(values.get(index), targetType.getComponentType()));
            }
            return array;
        }
        if (targetType == String.class && value instanceof String) return value;
        if ((targetType == Boolean.TYPE || targetType == Boolean.class) && value instanceof Boolean) return value;
        if ((targetType == Character.TYPE || targetType == Character.class)
                && value instanceof String && ((String) value).length() == 1) {
            return ((String) value).charAt(0);
        }
        if (value instanceof BigDecimal && isNumericType(targetType)) {
            BigDecimal number = (BigDecimal) value;
            try {
                if (targetType == Byte.TYPE || targetType == Byte.class) return number.byteValueExact();
                if (targetType == Short.TYPE || targetType == Short.class) return number.shortValueExact();
                if (targetType == Integer.TYPE || targetType == Integer.class) return number.intValueExact();
                if (targetType == Long.TYPE || targetType == Long.class) return number.longValueExact();
                if (targetType == Float.TYPE || targetType == Float.class) return number.floatValue();
                if (targetType == Double.TYPE || targetType == Double.class) return number.doubleValue();
                if (targetType == BigDecimal.class) return number;
                if (targetType == BigInteger.class) return number.toBigIntegerExact();
            } catch (ArithmeticException error) {
                throw new CheckSpecificationException("numeric argument is outside the target type range.");
            }
        }
        if (targetType == Object.class) return value;
        if (targetType.isEnum() && value instanceof String) {
            try {
                @SuppressWarnings({"unchecked", "rawtypes"})
                Object constant = Enum.valueOf((Class<? extends Enum>) targetType, (String) value);
                return constant;
            } catch (IllegalArgumentException error) {
                throw new CheckSpecificationException("unknown enum value '" + value + "'.");
            }
        }
        if (targetType.isInstance(value)) return value;
        throw new CheckSpecificationException(
                "JSON value cannot be converted to " + targetType.getTypeName() + ".");
    }

    private static boolean isNumericType(Class<?> type) {
        return type == Byte.TYPE || type == Byte.class || type == Short.TYPE || type == Short.class
                || type == Integer.TYPE || type == Integer.class || type == Long.TYPE || type == Long.class
                || type == Float.TYPE || type == Float.class || type == Double.TYPE || type == Double.class
                || type == BigDecimal.class || type == BigInteger.class;
    }

    private static Object toJsonValue(Object value) {
        if (value == null || value instanceof String || value instanceof Boolean || value instanceof BigDecimal) {
            return value;
        }
        if (value instanceof Character || value instanceof Enum) {
            return String.valueOf(value instanceof Enum ? ((Enum<?>) value).name() : value);
        }
        if (value instanceof BigInteger) return new BigDecimal((BigInteger) value);
        if (value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long) {
            return BigDecimal.valueOf(((Number) value).longValue());
        }
        if (value instanceof Float || value instanceof Double) {
            double number = ((Number) value).doubleValue();
            return Double.isFinite(number) ? BigDecimal.valueOf(number) : String.valueOf(number);
        }
        if (value.getClass().isArray()) {
            List<Object> result = new ArrayList<>();
            for (int index = 0; index < Array.getLength(value); index++) {
                result.add(toJsonValue(Array.get(value, index)));
            }
            return result;
        }
        if (value instanceof List) {
            List<Object> result = new ArrayList<>();
            for (Object item : (List<?>) value) result.add(toJsonValue(item));
            return result;
        }
        return "<instance of " + value.getClass().getTypeName() + ">";
    }

    private static boolean valuesEqual(Object expected, Object actual) {
        if (expected == null || actual == null) return expected == actual;
        if (expected instanceof BigDecimal && actual instanceof BigDecimal) {
            return ((BigDecimal) expected).compareTo((BigDecimal) actual) == 0;
        }
        if (expected instanceof List && actual instanceof List) {
            List<?> expectedValues = (List<?>) expected;
            List<?> actualValues = (List<?>) actual;
            if (expectedValues.size() != actualValues.size()) return false;
            for (int index = 0; index < expectedValues.size(); index++) {
                if (!valuesEqual(expectedValues.get(index), actualValues.get(index))) return false;
            }
            return true;
        }
        return expected.equals(actual);
    }

    private static String jsonText(Object value) {
        StringBuilder result = new StringBuilder();
        appendJsonValue(result, value);
        return result.toString();
    }

    private static void appendJsonValue(StringBuilder output, Object value) {
        if (value == null) {
            output.append("null");
        } else if (value instanceof String) {
            appendJsonString(output, (String) value);
        } else if (value instanceof Boolean) {
            output.append(value);
        } else if (value instanceof BigDecimal) {
            appendJsonNumber(output, (BigDecimal) value);
        } else if (value instanceof List) {
            output.append('[');
            List<?> values = (List<?>) value;
            for (int index = 0; index < values.size(); index++) {
                if (index > 0) output.append(',');
                appendJsonValue(output, values.get(index));
            }
            output.append(']');
        } else {
            appendJsonString(output, String.valueOf(value));
        }
    }

    private static String normalizeNewlines(String value) {
        return value.replace("\r\n", "\n");
    }

    private static String expandStringTemplate(String template, Object instance, Class<?> target)
            throws CheckFailure {
        Pattern placeholder = Pattern.compile("\\{([A-Za-z_$][A-Za-z0-9_$]*)\\}");
        Matcher matcher = placeholder.matcher(template);
        StringBuffer result = new StringBuffer();
        while (matcher.find()) {
            String fieldName = matcher.group(1);
            try {
                Field field = target.getDeclaredField(fieldName);
                field.setAccessible(true);
                Object value = field.get(instance);
                matcher.appendReplacement(result, Matcher.quoteReplacement(String.valueOf(value)));
            } catch (NoSuchFieldException error) {
                throw new CheckFailure("TEMPLATE_FIELD_NOT_FOUND", "<field " + fieldName + " not found>");
            } catch (IllegalAccessException | SecurityException error) {
                throw new CheckFailure("TEMPLATE_FIELD_ACCESS_ERROR: " + safeMessage(error), safeMessage(error));
            }
        }
        matcher.appendTail(result);
        return result.toString();
    }

    private static String optionalString(Map<?, ?> values, String key) throws CheckSpecificationException {
        if (!values.containsKey(key)) return null;
        Object value = values.get(key);
        if (!(value instanceof String)) {
            throw new CheckSpecificationException("'" + key + "' must be a string.");
        }
        return (String) value;
    }

    private static List<?> optionalArray(Map<?, ?> values, String key)
            throws CheckSpecificationException {
        if (!values.containsKey(key)) return List.of();
        Object value = values.get(key);
        if (!(value instanceof List)) {
            throw new CheckSpecificationException("'" + key + "' must be an array.");
        }
        return (List<?>) value;
    }

    private static List<?> requiredArray(Map<?, ?> values, String key)
            throws CheckSpecificationException {
        if (!values.containsKey(key) || !(values.get(key) instanceof List)) {
            throw new CheckSpecificationException("'" + key + "' must be an array.");
        }
        return (List<?>) values.get(key);
    }

    private static Map<?, ?> requireObject(Object value, String name)
            throws CheckSpecificationException {
        if (!(value instanceof Map)) {
            throw new CheckSpecificationException("'" + name + "' must be an object.");
        }
        return (Map<?, ?>) value;
    }

    private static Object requiredProperty(Map<?, ?> values, String key)
            throws CheckSpecificationException {
        if (!values.containsKey(key)) {
            throw new CheckSpecificationException("'" + key + "' is required.");
        }
        return values.get(key);
    }

    private static List<String> requiredTypeList(Map<?, ?> values, String key)
            throws CheckSpecificationException {
        return requiredTypeListValue(requiredProperty(values, key), key);
    }

    private static List<String> requiredTypeListValue(Object value, String key)
            throws CheckSpecificationException {
        if (!(value instanceof List)) {
            throw new CheckSpecificationException("'" + key + "' must be an array of type names.");
        }
        List<String> result = new ArrayList<>();
        for (Object item : (List<?>) value) {
            if (!(item instanceof String) || ((String) item).isBlank()) {
                throw new CheckSpecificationException("'" + key + "' entries must be non-empty strings.");
            }
            result.add((String) item);
        }
        return result;
    }

    private static String requiredString(SpecCheck check, String key)
            throws CheckSpecificationException {
        Object value = check.properties.get(key);
        if (!(value instanceof String) || ((String) value).isBlank()) {
            throw new CheckSpecificationException("'" + key + "' must be a non-empty string.");
        }
        return (String) value;
    }

    private static List<String> requiredTypeList(SpecCheck check, String key)
            throws CheckSpecificationException {
        Object value = check.properties.get(key);
        if (!(value instanceof List)) {
            throw new CheckSpecificationException("'" + key + "' must be an array of type names.");
        }
        List<String> result = new ArrayList<>();
        for (Object item : (List<?>) value) {
            if (!(item instanceof String) || ((String) item).isBlank()) {
                throw new CheckSpecificationException("'" + key + "' entries must be non-empty strings.");
            }
            result.add((String) item);
        }
        return result;
    }

    private static Set<String> requiredModifiers(SpecCheck check, String memberKind)
            throws CheckSpecificationException {
        Object value = check.properties.get("modifier");
        if (!check.properties.containsKey("modifier") || !(value instanceof String)) {
            throw new CheckSpecificationException("'modifier' must be a string.");
        }
        String text = (String) value;
        Set<String> allowed;
        switch (memberKind) {
            case "field":
                allowed = Set.of("public", "protected", "private", "static", "final", "transient", "volatile");
                break;
            case "constructor":
                allowed = Set.of("public", "protected", "private");
                break;
            case "method":
                allowed = Set.of(
                        "public", "protected", "private", "abstract", "static", "final",
                        "synchronized", "native", "strictfp", "default");
                break;
            default:
                throw new CheckSpecificationException("Unsupported member kind.");
        }

        Set<String> result = new HashSet<>();
        if (text.isBlank()) {
            return result;
        }
        for (String modifier : text.trim().split("\\s+")) {
            if (!allowed.contains(modifier) || !result.add(modifier)) {
                throw new CheckSpecificationException("Invalid or repeated modifier '" + modifier + "'.");
            }
        }
        return result;
    }

    private static Class<?>[] resolveParameterTypes(
            List<String> names, Class<?> target, ClassLoader loader)
            throws CheckSpecificationException {
        Class<?>[] result = new Class<?>[names.size()];
        for (int index = 0; index < names.size(); index++) {
            result[index] = resolveType(names.get(index), target, loader, false);
        }
        return result;
    }

    private static Class<?> resolveType(
            String name, Class<?> target, ClassLoader loader, boolean allowVoid)
            throws CheckSpecificationException {
        String baseName = name.trim();
        int dimensions = 0;
        while (baseName.endsWith("[]")) {
            dimensions++;
            baseName = baseName.substring(0, baseName.length() - 2);
        }
        if (baseName.isEmpty() || baseName.contains("[") || baseName.contains("]")) {
            throw new CheckSpecificationException("Invalid type name '" + name + "'.");
        }

        Class<?> resolved = primitiveType(baseName);
        if (resolved == null) {
            resolved = javaLangType(baseName);
        }
        if (resolved == null) {
            List<String> candidates = new ArrayList<>();
            if (!baseName.contains(".") && !target.getPackageName().isEmpty()) {
                candidates.add(target.getPackageName() + "." + baseName);
            }
            if (!baseName.contains(".")) {
                candidates.add("java.lang." + baseName);
            }
            candidates.add(baseName);
            for (String candidate : candidates) {
                if (!isBinaryClassName(candidate)) {
                    throw new CheckSpecificationException("Invalid type name '" + name + "'.");
                }
                try {
                    resolved = Class.forName(candidate, false, loader);
                    break;
                } catch (ClassNotFoundException ignored) {
                    // Try the fully qualified spelling if the package-local spelling misses.
                }
            }
        }
        if (resolved == null) {
            throw new CheckSpecificationException("Unknown type '" + name + "'.");
        }
        if (resolved == Void.TYPE && (!allowVoid || dimensions > 0)) {
            throw new CheckSpecificationException("void is not valid for type '" + name + "'.");
        }
        if (dimensions > 0) {
            resolved = Array.newInstance(resolved, new int[dimensions]).getClass();
        }
        return resolved;
    }

    private static Class<?> primitiveType(String name) {
        switch (name) {
            case "boolean": return Boolean.TYPE;
            case "byte": return Byte.TYPE;
            case "char": return Character.TYPE;
            case "short": return Short.TYPE;
            case "int": return Integer.TYPE;
            case "long": return Long.TYPE;
            case "float": return Float.TYPE;
            case "double": return Double.TYPE;
            case "void": return Void.TYPE;
            default: return null;
        }
    }

    private static Class<?> javaLangType(String name) {
        switch (name) {
            case "String":
            case "java.lang.String": return String.class;
            case "Boolean":
            case "java.lang.Boolean": return Boolean.class;
            case "Byte":
            case "java.lang.Byte": return Byte.class;
            case "Character":
            case "java.lang.Character": return Character.class;
            case "Short":
            case "java.lang.Short": return Short.class;
            case "Integer":
            case "java.lang.Integer": return Integer.class;
            case "Long":
            case "java.lang.Long": return Long.class;
            case "Float":
            case "java.lang.Float": return Float.class;
            case "Double":
            case "java.lang.Double": return Double.class;
            case "Object":
            case "java.lang.Object": return Object.class;
            case "Number":
            case "java.lang.Number": return Number.class;
            case "Void":
            case "java.lang.Void": return Void.class;
            case "Runnable":
            case "java.lang.Runnable": return Runnable.class;
            case "Comparable":
            case "java.lang.Comparable": return Comparable.class;
            case "Cloneable":
            case "java.lang.Cloneable": return Cloneable.class;
            case "AutoCloseable":
            case "java.lang.AutoCloseable": return AutoCloseable.class;
            case "Serializable":
            case "java.io.Serializable": return java.io.Serializable.class;
            default: return null;
        }
    }

    private static Set<String> actualModifiers(int modifiers, boolean defaultMethod) {
        Set<String> result = new HashSet<>();
        String text = Modifier.toString(modifiers);
        if (!text.isEmpty()) {
            result.addAll(Arrays.asList(text.split("\\s+")));
        }
        if (defaultMethod) {
            result.add("default");
        }
        return result;
    }

    private static String modifierText(int modifiers, boolean defaultMethod) {
        Set<String> values = actualModifiers(modifiers, defaultMethod);
        List<String> ordered = new ArrayList<>();
        String reflectionOrder = Modifier.toString(modifiers);
        if (!reflectionOrder.isEmpty()) {
            ordered.addAll(Arrays.asList(reflectionOrder.split("\\s+")));
        }
        if (defaultMethod) {
            ordered.add("default");
        }
        if (ordered.isEmpty() && values.isEmpty()) {
            return "";
        }
        return String.join(" ", ordered);
    }

    private static List<String> parameterTypeNames(Class<?>[] parameterTypes) {
        List<String> result = new ArrayList<>();
        for (Class<?> parameterType : parameterTypes) {
            result.add(parameterType.getTypeName());
        }
        return result;
    }

    private static String describeMethod(Method method) {
        return "name=" + method.getName() + ", parameter_types="
                + parameterTypeNames(method.getParameterTypes()) + ", return_type="
                + method.getReturnType().getTypeName() + ", modifier="
                + modifierText(method.getModifiers(), method.isDefault());
    }

    private static List<String> availableConstructors(Class<?> target) {
        List<String> result = new ArrayList<>();
        for (Constructor<?> constructor : target.getDeclaredConstructors()) {
            result.add("parameter_types=" + parameterTypeNames(constructor.getParameterTypes())
                    + ", modifier=" + modifierText(constructor.getModifiers(), false));
        }
        result.sort(Comparator.naturalOrder());
        return result;
    }

    private static List<String> availableMethods(Class<?> target, String name) {
        List<String> result = new ArrayList<>();
        for (Method method : target.getDeclaredMethods()) {
            if (method.getName().equals(name)) {
                result.add(describeMethod(method));
            }
        }
        result.sort(Comparator.naturalOrder());
        return result;
    }

    private static List<String> directInterfaceNames(Class<?> target) {
        List<String> result = new ArrayList<>();
        for (Class<?> interfaceType : target.getInterfaces()) {
            result.add(interfaceType.getTypeName());
        }
        result.sort(Comparator.naturalOrder());
        return result;
    }

    private static Method comparableMethod() throws CheckFailure {
        try {
            return Comparable.class.getMethod("compareTo", Object.class);
        } catch (NoSuchMethodException error) {
            throw new CheckFailure("JUDGE_INFRA_ERROR: Comparable.compareTo is unavailable.", null);
        }
    }

    private static Object invokeComparable(Method compareTo, Object left, Object right)
            throws CheckFailure {
        InvocationOutcome outcome = invokeMethod(compareTo, left, new Object[] {right});
        if (outcome.exception != null) {
            String errorCode = outcome.invocationError
                    ? "COMPARABLE_INVOCATION_ERROR" : "COMPARABLE_EXCEPTION";
            throw new CheckFailure(errorCode + ": " + exceptionText(outcome.exception),
                    exceptionText(outcome.exception));
        }
        if (!(outcome.value instanceof Integer)) {
            throw new CheckFailure("INVALID_COMPARABLE_RESULT", String.valueOf(outcome.value));
        }
        return outcome.value;
    }

    private static int requiredIndex(Map<?, ?> object, String key, int size)
            throws CheckSpecificationException {
        Object value = requiredProperty(object, key);
        if (!(value instanceof BigDecimal)) {
            throw new CheckSpecificationException("'" + key + "' must be an integer index.");
        }
        final int index;
        try {
            index = ((BigDecimal) value).intValueExact();
        } catch (ArithmeticException error) {
            throw new CheckSpecificationException("'" + key + "' must be an integer index.");
        }
        if (index < 0 || index >= size) {
            throw new CheckSpecificationException("'" + key + "' is outside the instances array.");
        }
        return index;
    }

    private static int requiredSign(Map<?, ?> object, String key)
            throws CheckSpecificationException {
        Object value = requiredProperty(object, key);
        if (!(value instanceof BigDecimal)) {
            throw new CheckSpecificationException("'" + key + "' must be -1, 0, or 1.");
        }
        final int sign;
        try {
            sign = ((BigDecimal) value).intValueExact();
        } catch (ArithmeticException error) {
            throw new CheckSpecificationException("'" + key + "' must be -1, 0, or 1.");
        }
        if (sign < -1 || sign > 1) {
            throw new CheckSpecificationException("'" + key + "' must be -1, 0, or 1.");
        }
        return sign;
    }

    private static List<Integer> requiredIndexList(Object raw, String key, int size)
            throws CheckSpecificationException {
        if (!(raw instanceof List) || ((List<?>) raw).size() != size) {
            throw new CheckSpecificationException("'" + key + "' must list every instance index once.");
        }
        List<Integer> result = new ArrayList<>();
        Set<Integer> unique = new HashSet<>();
        for (Object value : (List<?>) raw) {
            if (!(value instanceof BigDecimal)) {
                throw new CheckSpecificationException("'" + key + "' entries must be integer indices.");
            }
            final int index;
            try {
                index = ((BigDecimal) value).intValueExact();
            } catch (ArithmeticException error) {
                throw new CheckSpecificationException("'" + key + "' entries must be integer indices.");
            }
            if (index < 0 || index >= size || !unique.add(index)) {
                throw new CheckSpecificationException("'" + key + "' must list every instance index once.");
            }
            result.add(index);
        }
        return result;
    }

    private static String safeMessage(Throwable error) {
        if (error == null) {
            return "Unknown error.";
        }
        String message = error.getMessage();
        if (message == null || message.isBlank()) {
            return error.getClass().getName();
        }
        return error.getClass().getName() + ": " + message;
    }

    private static final class Spec {
        private final List<SpecCheck> checks;
        private final BigDecimal totalPoints;

        private Spec(List<SpecCheck> checks, BigDecimal totalPoints) {
            this.checks = List.copyOf(checks);
            this.totalPoints = totalPoints;
        }
    }

    private static final class SpecCheck {
        private final String id;
        private final String kind;
        private final BigDecimal points;
        private final Map<String, Object> properties;

        private SpecCheck(String id, String kind, BigDecimal points, Map<String, Object> properties) {
            this.id = id;
            this.kind = kind;
            this.points = points;
            this.properties = new LinkedHashMap<>(properties);
        }

        private String expectedDescription() {
            switch (kind) {
                case "field":
                    return "name=" + display("name") + ", type=" + display("type")
                            + ", modifier=" + display("modifier");
                case "constructor":
                    return "parameter_types=" + display("parameter_types")
                            + ", modifier=" + display("modifier");
                case "method":
                    return "name=" + display("name") + ", parameter_types="
                            + display("parameter_types") + ", return_type=" + display("return_type")
                            + ", modifier=" + display("modifier");
                case "implements":
                    return "implements " + display("interface");
                case "behavior":
                    return "method=" + display("method") + ", args=" + display("args")
                            + (properties.containsKey("expect_return")
                                    ? ", expect_return=" + display("expect_return") : "")
                            + (properties.containsKey("expect_state")
                                    ? ", expect_state=" + display("expect_state") : "")
                            + (properties.containsKey("expect_exception")
                                    ? ", expect_exception=" + display("expect_exception") : "");
                case "toString":
                    return "template=" + display("template");
                case "comparable":
                    return "comparisons=" + display("comparisons")
                            + ", expected_order=" + display("expected_order");
                default:
                    return "kind=" + kind;
            }
        }

        private String display(String key) {
            Object value = properties.get(key);
            return properties.containsKey(key) ? String.valueOf(value) : "<missing>";
        }
    }

    private static final class CheckResult {
        private final String id;
        private final boolean passed;
        private final BigDecimal pointsEarned;
        private final String expected;
        private final String actual;
        private final String error;

        private CheckResult(
                String id,
                boolean passed,
                BigDecimal pointsEarned,
                String expected,
                String actual,
                String error) {
            this.id = id;
            this.passed = passed;
            this.pointsEarned = pointsEarned;
            this.expected = expected;
            this.actual = actual;
            this.error = error;
        }

        private static CheckResult evaluated(
                SpecCheck check, boolean passed, String expected, String actual, String error) {
            return new CheckResult(
                    check.id,
                    passed,
                    passed ? check.points : BigDecimal.ZERO,
                    expected,
                    actual,
                    error);
        }

        private static CheckResult failed(
                SpecCheck check, String expected, String actual, String error) {
            return evaluated(check, false, expected, actual, error);
        }

        private void appendJson(StringBuilder json) {
            json.append("{\"id\":");
            appendJsonString(json, id);
            json.append(",\"passed\":").append(passed).append(",\"points_earned\":");
            appendJsonNumber(json, pointsEarned);
            json.append(",\"expected\":");
            appendNullableString(json, expected);
            json.append(",\"actual\":");
            appendNullableString(json, actual);
            json.append(",\"error\":");
            appendNullableString(json, error);
            json.append('}');
        }
    }

    private static final class Response {
        private final BigDecimal score;
        private final BigDecimal totalPoints;
        private final List<CheckResult> checks;
        private final String errorCategory;
        private final String failureType;
        private final String error;

        private Response(
                BigDecimal score,
                BigDecimal totalPoints,
                List<CheckResult> checks,
                String errorCategory,
                String failureType,
                String error) {
            this.score = score;
            this.totalPoints = totalPoints;
            this.checks = List.copyOf(checks);
            this.errorCategory = errorCategory;
            this.failureType = failureType;
            this.error = error;
        }

        private static Response success(BigDecimal score, BigDecimal totalPoints, List<CheckResult> results) {
            return new Response(score, totalPoints, results, null, null, null);
        }

        private static Response failure(
                BigDecimal totalPoints,
                List<CheckResult> checks,
                String errorCategory,
                String failureType,
                String error) {
            return new Response(
                    BigDecimal.ZERO,
                    totalPoints,
                    checks,
                    errorCategory,
                    failureType,
                    error);
        }

        private String toJson() {
            StringBuilder json = new StringBuilder(128 + checks.size() * 96);
            json.append("{\"score\":");
            appendJsonNumber(json, score);
            json.append(",\"total_points\":");
            appendJsonNumber(json, totalPoints);
            json.append(",\"checks\":[");
            for (int index = 0; index < checks.size(); index++) {
                if (index > 0) {
                    json.append(',');
                }
                checks.get(index).appendJson(json);
            }
            json.append("],\"error_category\":");
            appendNullableString(json, errorCategory);
            json.append(",\"failure_type\":");
            appendNullableString(json, failureType);
            json.append(",\"error\":");
            appendNullableString(json, error);
            json.append('}');
            return json.toString();
        }
    }

    private static final class ProtocolChannel {
        private final PrintStream output;
        private boolean written;
        private Response emergencyResponse;

        private ProtocolChannel(PrintStream output) {
            this.output = output;
        }

        private synchronized void armForStudentExecution(Spec spec) {
            String message = "Student code terminated the Judge JVM with System.exit().";
            List<CheckResult> checks = new ArrayList<>();
            for (SpecCheck check : spec.checks) {
                checks.add(CheckResult.failed(
                        check,
                        check.expectedDescription(),
                        "<judge process terminated>",
                        "STUDENT_PROCESS_EXIT: " + message));
            }
            emergencyResponse = Response.failure(
                    spec.totalPoints,
                    checks,
                    null,
                    "STUDENT_PROCESS_EXIT",
                    message);
        }

        private synchronized void writeEmergencyResponse() {
            if (!written && emergencyResponse != null) {
                writeLocked(emergencyResponse);
            }
        }

        private synchronized void write(Response response) {
            if (!written) {
                writeLocked(response);
            }
        }

        private void writeLocked(Response response) {
            written = true;
            byte[] bytes = response.toJson().getBytes(StandardCharsets.UTF_8);
            output.write(bytes, 0, bytes.length);
            output.write('\n');
            output.flush();
        }
    }

    private static void appendNullableString(StringBuilder output, String value) {
        if (value == null) {
            output.append("null");
        } else {
            appendJsonString(output, value);
        }
    }

    private static void appendJsonNumber(StringBuilder output, BigDecimal value) {
        BigDecimal normalized = value.stripTrailingZeros();
        output.append(normalized.signum() == 0 ? "0" : normalized.toString());
    }

    private static void appendJsonString(StringBuilder output, String value) {
        output.append('"');
        final char[] hex = "0123456789abcdef".toCharArray();
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            switch (character) {
                case '"': output.append("\\\""); break;
                case '\\': output.append("\\\\"); break;
                case '\b': output.append("\\b"); break;
                case '\f': output.append("\\f"); break;
                case '\n': output.append("\\n"); break;
                case '\r': output.append("\\r"); break;
                case '\t': output.append("\\t"); break;
                default:
                    if (character < 0x20 || Character.isSurrogate(character)) {
                        output.append("\\u");
                        output.append(hex[(character >>> 12) & 0x0f]);
                        output.append(hex[(character >>> 8) & 0x0f]);
                        output.append(hex[(character >>> 4) & 0x0f]);
                        output.append(hex[character & 0x0f]);
                    } else {
                        output.append(character);
                    }
            }
        }
        output.append('"');
    }

    private static final class DiscardingOutputStream extends OutputStream {
        @Override
        public void write(int value) {
            // Student stdout is intentionally isolated from the JSON result channel.
        }

        @Override
        public void write(byte[] bytes, int offset, int length) {
            // Discard without buffering so arbitrary static-initializer output is bounded.
        }
    }

    private static final class InvalidSpecificationException extends Exception {
        private InvalidSpecificationException(String message) {
            super(message);
        }
    }

    private static final class CheckSpecificationException extends Exception {
        private CheckSpecificationException(String message) {
            super(message);
        }
    }

    private static final class CheckFailure extends Exception {
        private final String code;
        private final String actual;

        private CheckFailure(String code, String actual) {
            super(code);
            this.code = code;
            this.actual = actual;
        }
    }

    private static final class InvocationOutcome {
        private final Object value;
        private final Throwable exception;
        private final boolean invocationError;

        private InvocationOutcome(Object value, Throwable exception, boolean invocationError) {
            this.value = value;
            this.exception = exception;
            this.invocationError = invocationError;
        }
    }

    private static final class ComparableCheckRuntimeException extends RuntimeException {
        private final CheckFailure failure;

        private ComparableCheckRuntimeException(CheckFailure failure) {
            this.failure = failure;
        }
    }

    private static final class ProtocolInputException extends Exception {
        private ProtocolInputException(String message) {
            super(message);
        }
    }

    private static final class JsonParser {
        private final String input;
        private int offset;

        private JsonParser(String input) {
            this.input = input;
        }

        private Object parse() throws InvalidSpecificationException {
            skipWhitespace();
            Object value = parseValue(0);
            skipWhitespace();
            if (offset != input.length()) {
                fail("Unexpected data after the JSON value");
            }
            return value;
        }

        private Object parseValue(int depth) throws InvalidSpecificationException {
            if (depth > MAX_JSON_DEPTH) {
                fail("JSON nesting limit exceeded");
            }
            skipWhitespace();
            if (offset >= input.length()) {
                fail("Unexpected end of JSON input");
            }
            char current = input.charAt(offset);
            if (current == '{') return parseObject(depth + 1);
            if (current == '[') return parseArray(depth + 1);
            if (current == '"') return parseString();
            if (current == 't') return parseLiteral("true", Boolean.TRUE);
            if (current == 'f') return parseLiteral("false", Boolean.FALSE);
            if (current == 'n') return parseLiteral("null", null);
            if (current == '-' || (current >= '0' && current <= '9')) return parseNumber();
            fail("Unexpected character '" + current + "'");
            return null;
        }

        private Map<String, Object> parseObject(int depth) throws InvalidSpecificationException {
            expect('{');
            skipWhitespace();
            Map<String, Object> result = new LinkedHashMap<>();
            if (consume('}')) return result;
            while (true) {
                skipWhitespace();
                if (offset >= input.length() || input.charAt(offset) != '"') {
                    fail("Object keys must be strings");
                }
                String key = parseString();
                skipWhitespace();
                expect(':');
                Object value = parseValue(depth);
                if (result.containsKey(key)) {
                    fail("Duplicate object key '" + key + "'");
                }
                result.put(key, value);
                skipWhitespace();
                if (consume('}')) return result;
                expect(',');
            }
        }

        private List<Object> parseArray(int depth) throws InvalidSpecificationException {
            expect('[');
            skipWhitespace();
            List<Object> result = new ArrayList<>();
            if (consume(']')) return result;
            while (true) {
                result.add(parseValue(depth));
                skipWhitespace();
                if (consume(']')) return result;
                expect(',');
            }
        }

        private String parseString() throws InvalidSpecificationException {
            expect('"');
            StringBuilder result = new StringBuilder();
            while (offset < input.length()) {
                char current = input.charAt(offset++);
                if (current == '"') return result.toString();
                if (current < 0x20) fail("Unescaped control character in string");
                if (current != '\\') {
                    result.append(current);
                    continue;
                }
                if (offset >= input.length()) fail("Incomplete string escape");
                char escape = input.charAt(offset++);
                switch (escape) {
                    case '"': result.append('"'); break;
                    case '\\': result.append('\\'); break;
                    case '/': result.append('/'); break;
                    case 'b': result.append('\b'); break;
                    case 'f': result.append('\f'); break;
                    case 'n': result.append('\n'); break;
                    case 'r': result.append('\r'); break;
                    case 't': result.append('\t'); break;
                    case 'u': result.append(parseUnicodeEscape()); break;
                    default: fail("Invalid string escape");
                }
            }
            fail("Unterminated string");
            return null;
        }

        private char parseUnicodeEscape() throws InvalidSpecificationException {
            if (input.length() - offset < 4) fail("Incomplete Unicode escape");
            int value = 0;
            for (int count = 0; count < 4; count++) {
                char character = input.charAt(offset++);
                int digit;
                if (character >= '0' && character <= '9') {
                    digit = character - '0';
                } else if (character >= 'a' && character <= 'f') {
                    digit = character - 'a' + 10;
                } else if (character >= 'A' && character <= 'F') {
                    digit = character - 'A' + 10;
                } else {
                    digit = -1;
                }
                if (digit < 0) fail("Invalid Unicode escape");
                value = (value << 4) | digit;
            }
            return (char) value;
        }

        private Object parseNumber() throws InvalidSpecificationException {
            int start = offset;
            consume('-');
            if (consume('0')) {
                if (offset < input.length() && isDigit(input.charAt(offset))) {
                    fail("Leading zero in number");
                }
            } else {
                requireDigits();
            }
            if (consume('.')) requireDigits();
            if (consume('e') || consume('E')) {
                if (!consume('+')) consume('-');
                requireDigits();
            }
            try {
                return new BigDecimal(input.substring(start, offset));
            } catch (NumberFormatException error) {
                fail("Invalid number");
                return null;
            }
        }

        private Object parseLiteral(String expected, Object value)
                throws InvalidSpecificationException {
            if (!input.startsWith(expected, offset)) fail("Invalid JSON literal");
            offset += expected.length();
            return value;
        }

        private void requireDigits() throws InvalidSpecificationException {
            int start = offset;
            while (offset < input.length() && isDigit(input.charAt(offset))) offset++;
            if (start == offset) fail("Expected a digit");
        }

        private boolean isDigit(char value) {
            return value >= '0' && value <= '9';
        }

        private void skipWhitespace() {
            while (offset < input.length()) {
                char value = input.charAt(offset);
                if (value == ' ' || value == '\t' || value == '\r' || value == '\n') {
                    offset++;
                } else {
                    return;
                }
            }
        }

        private boolean consume(char expected) {
            if (offset < input.length() && input.charAt(offset) == expected) {
                offset++;
                return true;
            }
            return false;
        }

        private void expect(char expected) throws InvalidSpecificationException {
            if (!consume(expected)) fail("Expected '" + expected + "'");
        }

        private void fail(String message) throws InvalidSpecificationException {
            throw new InvalidSpecificationException(message + " at character " + offset + ".");
        }
    }
}
