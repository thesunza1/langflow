import { expect, test } from "../../fixtures";
import { awaitBootstrapTest } from "../../utils/await-bootstrap-test";

test(
  "RunModeModal popup appears after upstream component is built",
  {
    tag: ["@release", "@workspace"],
  },
  async ({ page }) => {
    // Navigate to homepage
    await awaitBootstrapTest(page);

    // Start with blank flow
    await page.getByTestId("blank-flow").click();
    await page.waitForSelector('[data-testid="sidebar-search-input"]', {
      timeout: 5000,
    });

    // Add Chat Input component
    await page.getByTestId("sidebar-search-input").click();
    await page.getByTestId("sidebar-search-input").fill("Chat Input");
    await page.waitForSelector('[data-testid="input_outputChat Input"]', {
      timeout: 3000,
    });
    await page.getByTestId("input_outputChat Input").hover();
    await page.getByTestId("icon-Plus").click();
    await page.waitForTimeout(500);

    // Add Text Output component
    await page.getByTestId("sidebar-search-input").fill("Text Output");
    await page.waitForSelector('[data-testid="input_outputText Output"]', {
      timeout: 3000,
    });
    await page.getByTestId("input_outputText Output").hover();
    await page.getByTestId("icon-Plus").click();
    await page.waitForTimeout(500);

    // Connect Chat Input to Text Output
    // Get the nodes
    const nodes = page.locator(".react-flow__node");
    await expect(nodes).toHaveCount(2);

    // Run the Chat Input component first (so it gets built)
    const chatInputRunButton = page.getByTestId("button_run_chat input");
    await expect(chatInputRunButton).toBeVisible({ timeout: 5000 });
    await chatInputRunButton.click();

    // Wait for the build to complete
    await page.waitForTimeout(3000);

    // Click Run on Text Output component
    const textOutputRunButton = page.getByTestId("button_run_text output");
    await expect(textOutputRunButton).toBeVisible({ timeout: 5000 });
    await textOutputRunButton.click();

    // Verify the RunModeModal popup appears
    await expect(page.getByTestId("run-mode-radio-group")).toBeVisible({
      timeout: 5000,
    });

    // Verify both radio options are present
    await expect(page.getByTestId("radio-run-from-nearest")).toBeVisible();
    await expect(page.getByTestId("radio-run-from-start")).toBeVisible();

    // Verify the Run and Cancel buttons are present
    await expect(page.getByTestId("run-mode-run-button")).toBeVisible();
    await expect(page.getByTestId("run-mode-cancel-button")).toBeVisible();

    // Click Cancel to close the modal
    await page.getByTestId("run-mode-cancel-button").click();
    await expect(page.getByTestId("run-mode-radio-group")).not.toBeVisible({
      timeout: 3000,
    });
  },
);
